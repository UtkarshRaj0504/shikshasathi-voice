"""
Tests for teacher voice cloning (/voice-profiles) — all mocked, no network.

Covers: consent gate, role checks, teacher isolation, audio validation, profile
cap, rate limiting, revoke/delete flows, provider error mapping, the cloned-voice
disclosure label and graceful fallback in /tts/speak, and that students never
receive reference audio.
"""

import struct
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import status

from app.api.voice_profiles import reset_rate_limits
from app.models.voice_consent import VoiceConsent
from app.models.voice_profile import VoiceProfile
from app.services.voice_clone_service import GnaniVoiceCloneService, VoiceCloneError


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def make_wav(seconds: float, sample_rate: int = 16000) -> bytes:
    """Build a valid mono 16-bit PCM WAV of the requested length."""
    num_samples = int(seconds * sample_rate)
    data = b"\x00\x00" * num_samples
    header = bytearray()
    header.extend(b"RIFF")
    header.extend(struct.pack("<I", 36 + len(data)))
    header.extend(b"WAVEfmt ")
    header.extend(struct.pack("<I", 16))
    header.extend(struct.pack("<H", 1))  # PCM
    header.extend(struct.pack("<H", 1))  # mono
    header.extend(struct.pack("<I", sample_rate))
    header.extend(struct.pack("<I", sample_rate * 2))  # byte rate
    header.extend(struct.pack("<H", 2))  # block align
    header.extend(struct.pack("<H", 16))  # bits per sample
    header.extend(b"data")
    header.extend(struct.pack("<I", len(data)))
    return bytes(header + data)


VALID_WAV = make_wav(10)  # 10 s -> inside the 5-30 s window


def make_webm_opus(seconds: float = 6.0, rate: int = 48000) -> bytes | None:
    """Encode a speech-like mono signal as WebM/Opus — what a browser records.

    Returns None when PyAV / libopus is unavailable so the WebM tests can skip
    instead of failing on a machine without the encoder.
    """
    try:
        import io

        import av
        import numpy as np
    except Exception:  # pragma: no cover - PyAV is a declared dependency
        return None

    n = int(seconds * rate)
    t = np.arange(n) / rate
    pcm = (0.3 * 32767 * np.sin(2 * np.pi * 220.0 * t)).astype("<i2")

    buf = io.BytesIO()
    try:
        with av.open(buf, mode="w", format="webm") as out:
            stream = out.add_stream("libopus", rate=rate)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
            frame.rate = rate
            frame.pts = 0
            for packet in stream.encode(frame):
                out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
    except Exception:  # pragma: no cover - encoder missing
        return None
    return buf.getvalue()


WEBM_OPUS = make_webm_opus(6.0)


def register_and_login(client, email, role, name="User"):
    client.post(
        "/auth/register",
        json={"email": email, "name": name, "password": "password123", "role": role},
    )
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_profile(client, token, name="My Voice", wav=VALID_WAV, consented=True, languages="en"):
    data = {"voice_name": name}
    if consented:
        data["consent_confirmed"] = "true"
    if languages:
        data["languages"] = languages
    return client.post(
        "/voice-profiles",
        headers=_auth(token),
        data=data,
        files={"file": ("sample.wav", wav, "audio/wav")},
    )


# --------------------------------------------------------------------------- #
# Consent + role checks
# --------------------------------------------------------------------------- #

def test_student_forbidden_on_teacher_endpoints(client):
    token = register_and_login(client, "s1@example.com", "student")
    assert client.get("/voice-profiles", headers=_auth(token)).status_code == 403
    assert client.get("/voice-profiles/consent", headers=_auth(token)).status_code == 403
    res = client.post(
        "/voice-profiles",
        headers=_auth(token),
        data={"voice_name": "X", "consent_confirmed": "true"},
        files={"file": ("sample.wav", VALID_WAV, "audio/wav")},
    )
    assert res.status_code == 403


def test_unauthenticated_rejected(client):
    assert client.get("/voice-profiles").status_code == 401


def test_consent_details_before_confirmation(client):
    token = register_and_login(client, "t_consent@example.com", "teacher", "Dr. A")
    res = client.get("/voice-profiles/consent", headers=_auth(token))
    assert res.status_code == 200
    body = res.json()
    assert body["confirmed"] is False
    assert len(body["consent_text"]) > 100
    assert body["max_profiles"] >= 1


def test_create_without_consent_rejected_and_no_profile(client, db_session):
    token = register_and_login(client, "t_noconsent@example.com", "teacher", "Dr. B")
    res = _create_profile(client, token, consented=False)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "CONSENT_REQUIRED"
    # No profile may exist without consent.
    assert db_session.query(VoiceProfile).count() == 0


def test_create_with_consent_activates_and_records_consent(client, db_session):
    token = register_and_login(client, "t_ok@example.com", "teacher", "Dr. C")
    res = _create_profile(client, token)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "active"
    assert body["consent_confirmed"] is True
    assert body["voice_name"] == "My Voice"

    profile = db_session.get(VoiceProfile, body["id"])
    assert profile.status == "active"
    assert profile.gnani_voice_id  # embedding reference stored

    consents = db_session.query(VoiceConsent).filter(VoiceConsent.voice_profile_id == profile.id).all()
    assert len(consents) == 1
    assert consents[0].confirmed is True
    assert consents[0].full_consent_text
    assert consents[0].consent_text_version


def test_consent_details_after_creation(client):
    token = register_and_login(client, "t_after@example.com", "teacher", "Dr. D")
    _create_profile(client, token)
    res = client.get("/voice-profiles/consent", headers=_auth(token))
    assert res.json()["confirmed"] is True


# --------------------------------------------------------------------------- #
# Audio validation
# --------------------------------------------------------------------------- #

def test_unsupported_file_type_rejected(client):
    token = register_and_login(client, "t_type@example.com", "teacher")
    res = client.post(
        "/voice-profiles",
        headers=_auth(token),
        data={"voice_name": "V", "consent_confirmed": "true"},
        files={"file": ("notes.txt", b"not audio at all " * 100, "text/plain")},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_AUDIO"


def test_too_small_sample_rejected(client):
    token = register_and_login(client, "t_small@example.com", "teacher")
    res = _create_profile(client, token, wav=b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 20)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_AUDIO"


def test_too_short_duration_rejected(client):
    token = register_and_login(client, "t_short@example.com", "teacher")
    res = _create_profile(client, token, wav=make_wav(2))
    assert res.status_code == 400
    assert "5 seconds" in res.json()["detail"]["message"]


def test_too_long_duration_rejected(client):
    token = register_and_login(client, "t_long@example.com", "teacher")
    res = _create_profile(client, token, wav=make_wav(40))
    assert res.status_code == 400
    assert "30 seconds" in res.json()["detail"]["message"]


def test_normalize_reference_audio_outputs_16k_mono_wav():
    """A WAV upload is normalized to the 16 kHz mono shape the provider expects."""
    from app.services.audio_utils import _wav_duration_seconds, normalize_reference_audio

    wav = normalize_reference_audio(VALID_WAV)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert struct.unpack("<H", wav[22:24])[0] == 1  # mono
    assert struct.unpack("<I", wav[24:28])[0] == 16000  # sample rate
    duration = _wav_duration_seconds(wav)
    assert duration is not None and 9.0 < duration < 11.0


def test_normalize_reference_audio_rejects_undecodable():
    """Undecodable bytes must raise a clear error — never reach the provider as a 500."""
    from app.services.audio_utils import AudioValidationError, normalize_reference_audio

    with pytest.raises(AudioValidationError):
        normalize_reference_audio(b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 5000)


@pytest.mark.skipif(WEBM_OPUS is None, reason="PyAV WebM/Opus encoder unavailable")
def test_webm_recording_is_transcoded_and_accepted(client, db_session):
    """A browser WebM/Opus recording must be transcoded, not sent raw (provider 500s)."""
    token = register_and_login(client, "t_webm@example.com", "teacher")
    res = client.post(
        "/voice-profiles",
        headers=_auth(token),
        data={"voice_name": "WebM Voice", "consent_confirmed": "true", "languages": "en"},
        files={"file": ("sample.webm", WEBM_OPUS, "audio/webm")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "active"
    assert db_session.get(VoiceProfile, res.json()["id"]).gnani_voice_id


def test_empty_voice_name_rejected(client):
    token = register_and_login(client, "t_name@example.com", "teacher")
    res = _create_profile(client, token, name="   ")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_NAME"


# --------------------------------------------------------------------------- #
# Teacher isolation
# --------------------------------------------------------------------------- #

def test_teacher_cannot_see_other_teachers_profiles(client):
    tok_a = register_and_login(client, "ta@example.com", "teacher", "Teacher A")
    tok_b = register_and_login(client, "tb@example.com", "teacher", "Teacher B")
    _create_profile(client, tok_a, name="A's voice")

    res = client.get("/voice-profiles", headers=_auth(tok_b))
    assert res.status_code == 200
    assert res.json()["profiles"] == []


def test_teacher_cannot_preview_delete_or_revoke_other_teacher_profile(client):
    tok_a = register_and_login(client, "ta2@example.com", "teacher", "Teacher A")
    tok_b = register_and_login(client, "tb2@example.com", "teacher", "Teacher B")
    profile_id = _create_profile(client, tok_a, name="A's voice").json()["id"]

    assert client.post(f"/voice-profiles/{profile_id}/preview", headers=_auth(tok_b)).status_code == 404
    assert client.delete(f"/voice-profiles/{profile_id}", headers=_auth(tok_b)).status_code == 404
    assert client.post(f"/voice-profiles/{profile_id}/revoke", headers=_auth(tok_b)).status_code == 404


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #

def test_preview_returns_audio_and_disclosure_label(client):
    token = register_and_login(client, "t_prev@example.com", "teacher")
    profile_id = _create_profile(client, token).json()["id"]

    res = client.post(f"/voice-profiles/{profile_id}/preview", headers=_auth(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["label"] == "AI-generated voice, authorized by the teacher."
    assert body["audio_base64"]
    assert body["is_mock"] is True  # tests always run the mock provider


def test_preview_inactive_profile_rejected(client, db_session):
    token = register_and_login(client, "t_prev2@example.com", "teacher")
    profile = VoiceProfile(
        teacher_id=1, voice_name="Pending", status="pending", consent_confirmed=False
    )
    db_session.add(profile)
    db_session.commit()
    res = client.post(f"/voice-profiles/{profile.id}/preview", headers=_auth(token))
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "PROFILE_NOT_ACTIVE"


# --------------------------------------------------------------------------- #
# Revoke / delete
# --------------------------------------------------------------------------- #

def test_revoke_removes_voice_and_tts_falls_back(client):
    token = register_and_login(client, "t_rev@example.com", "teacher")
    profile_id = _create_profile(client, token, name="Revoke Me").json()["id"]

    # Visible to students while active.
    student = register_and_login(client, "s_rev@example.com", "student")
    voices = client.get("/voices", headers=_auth(student)).json()
    assert any(v["id"] == profile_id for v in voices)

    res = client.post(f"/voice-profiles/{profile_id}/revoke", headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["status"] == "revoked"
    assert res.json()["consent_confirmed"] is False

    # Removed from the student voice list.
    voices = client.get("/voices", headers=_auth(student)).json()
    assert all(v["id"] != profile_id for v in voices)

    # /tts/speak falls back to the default voice, never a beep.
    speak = client.post(
        "/tts/speak",
        headers=_auth(student),
        json={"text": "Hello there", "voice_profile_id": profile_id, "language": "en"},
    )
    assert speak.status_code == 200, speak.text
    body = speak.json()
    assert body["fallback"] is True
    assert body["is_cloned"] is False
    assert body["voice_used"] == "default"
    assert body["audio_base64"]


def test_delete_removes_profile_and_revokes_consent(client, db_session):
    token = register_and_login(client, "t_del@example.com", "teacher")
    profile_id = _create_profile(client, token, name="Delete Me").json()["id"]

    res = client.delete(f"/voice-profiles/{profile_id}", headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["status"] == "deleted"

    assert db_session.get(VoiceProfile, profile_id) is None
    # The consent audit trail survives the profile deletion (the FK is detached).
    consents = db_session.query(VoiceConsent).all()
    assert consents and all(c.revoked_at is not None for c in consents)


# --------------------------------------------------------------------------- #
# Cloned playback via /tts/speak
# --------------------------------------------------------------------------- #

def test_tts_speak_uses_cloned_voice_with_label(client):
    token = register_and_login(client, "t_tts@example.com", "teacher")
    profile_id = _create_profile(client, token).json()["id"]

    student = register_and_login(client, "s_tts@example.com", "student")
    res = client.post(
        "/tts/speak",
        headers=_auth(student),
        json={"text": "Explain photosynthesis", "voice_profile_id": profile_id, "language": "en"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["is_cloned"] is True
    assert body["voice_used"] == "cloned"
    assert body["fallback"] is False
    assert body["label"] == "AI-generated voice, authorized by the teacher."


# --------------------------------------------------------------------------- #
# Students never receive reference audio
# --------------------------------------------------------------------------- #

def test_voices_list_never_exposes_reference_audio(client):
    token = register_and_login(client, "t_sec@example.com", "teacher")
    _create_profile(client, token, name="Secure Voice")
    student = register_and_login(client, "s_sec@example.com", "student")

    voices = client.get("/voices", headers=_auth(student)).json()
    assert voices
    for v in voices:
        assert "audio" not in str(v.keys()).lower()
        assert "sample_audio_path" not in v
        assert "gnani_voice_id" not in v
        assert "consent_text" not in v


# --------------------------------------------------------------------------- #
# Profile cap + rate limiting
# --------------------------------------------------------------------------- #

def test_profile_cap_enforced(client):
    token = register_and_login(client, "t_cap@example.com", "teacher")
    for i in range(3):
        assert _create_profile(client, token, name=f"Voice {i}").status_code == 200

    res = _create_profile(client, token, name="One too many")
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "PROFILE_LIMIT_REACHED"


def test_failed_profiles_do_not_count_toward_cap(client, monkeypatch):
    """A rejected attempt leaves a 'failed' row, but must never consume a slot.

    Otherwise a few failed retries block the feature with an opaque HTTP 400 even
    though the teacher has no usable voice at all.
    """
    from app.api import voice_profiles as vp
    from app.services.voice_clone_service import MockVoiceCloneService

    class _FailingService:
        is_mock = False

        def create_voice(self, audio_bytes, filename="sample.wav"):
            raise VoiceCloneError("nope", status_code=502, error_code="VOICE_CLONE_FORBIDDEN")

    monkeypatch.setattr(vp, "get_voice_clone_service", lambda: _FailingService())
    token = register_and_login(client, "t_capfail@example.com", "teacher")
    for i in range(3):
        res = _create_profile(client, token, name=f"Failed {i}")
        assert res.status_code == 502
        assert res.json()["detail"]["code"] == "VOICE_CLONE_FORBIDDEN"

    # The teacher has 3 "failed" profiles but 0 usable ones -> creation must still work.
    monkeypatch.setattr(vp, "get_voice_clone_service", lambda: MockVoiceCloneService())
    ok = _create_profile(client, token, name="Real Voice")
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "active"


def test_create_rate_limited(client, monkeypatch):
    from app.api import voice_profiles as vp
    from app.core.config import settings

    monkeypatch.setattr(settings, "VOICE_CLONE_CREATE_RATE_LIMIT", 2)
    monkeypatch.setattr(settings, "VOICE_CLONE_MAX_PROFILES", 100)
    token = register_and_login(client, "t_rate@example.com", "teacher")

    assert _create_profile(client, token, name="V1").status_code == 200
    assert _create_profile(client, token, name="V2").status_code == 200
    res = _create_profile(client, token, name="V3")
    assert res.status_code == 429
    assert res.json()["detail"]["code"] == "VOICE_CLONE_RATE_LIMIT"
    _ = vp


# --------------------------------------------------------------------------- #
# Provider error mapping (service level, httpx mocked — no network)
# --------------------------------------------------------------------------- #

def _fake_response(status_code, json_body=None, text=""):
    res = MagicMock()
    res.status_code = status_code
    res.json.return_value = json_body or {}
    res.text = text
    return res


@pytest.mark.parametrize(
    "http_status,expected_code,expected_status",
    [
        (401, "VOICE_CLONE_AUTH", 502),
        (402, "VOICE_CLONE_QUOTA", 502),
        (403, "VOICE_CLONE_FORBIDDEN", 502),
        (429, "VOICE_CLONE_RATE_LIMIT", 429),
        (400, "VOICE_CLONE_BAD_AUDIO", 400),
        (500, "VOICE_CLONE_PROVIDER_ERROR", 502),
    ],
)
@patch("app.services.voice_clone_service.time.sleep")
@patch("app.services.voice_clone_service.httpx.Client")
def test_gnani_create_voice_error_mapping(mock_client, mock_sleep, http_status, expected_code, expected_status):
    mock_client.return_value.__enter__.return_value.post.return_value = _fake_response(
        http_status, {"detail": {"error_code": "X", "message": "boom"}}, text="boom"
    )
    svc = GnaniVoiceCloneService(api_key="dummy-key")
    with pytest.raises(VoiceCloneError) as exc:
        svc.create_voice(b"x" * 2000, "sample.wav")
    assert exc.value.error_code == expected_code
    assert exc.value.status_code == expected_status


@patch("app.services.voice_clone_service.time.sleep")
@patch("app.services.voice_clone_service.httpx.Client")
def test_gnani_create_voice_retries_transient_500(mock_client, mock_sleep):
    """HTTP 500 on the embeddings endpoint is documented as retryable with backoff."""
    post = mock_client.return_value.__enter__.return_value.post
    post.side_effect = [
        _fake_response(
            500,
            {"success": False, "message": "We are facing technical difficulties.", "status_code": 500},
            text="raw",
        ),
        _fake_response(
            200,
            {
                "success": True,
                "data": {
                    "voice_clone_embedding": {
                        "embedding": "abc123",
                        "shape": [1, 768],
                        "dtype": "torch.bfloat16",
                    }
                },
            },
        ),
    ]
    svc = GnaniVoiceCloneService(api_key="dummy-key")
    ref = svc.create_voice(b"x" * 2000, "sample.wav")
    assert "abc123" in ref
    assert post.call_count == 2
    mock_sleep.assert_called_once_with(0.5)


@patch("app.services.voice_clone_service.time.sleep")
@patch("app.services.voice_clone_service.httpx.Client")
def test_persistent_500_surfaces_provider_message(mock_client, mock_sleep):
    """A 500 that keeps failing must report Gnani's own flat-body message, not a bare code."""
    mock_client.return_value.__enter__.return_value.post.return_value = _fake_response(
        500,
        {"success": False, "message": "We are facing technical difficulties.", "status_code": 500},
        text="raw",
    )
    svc = GnaniVoiceCloneService(api_key="dummy-key")
    with pytest.raises(VoiceCloneError) as exc:
        svc.create_voice(b"x" * 2000, "sample.wav")
    assert exc.value.error_code == "VOICE_CLONE_PROVIDER_ERROR"
    assert exc.value.status_code == 502
    assert "technical difficulties" in exc.value.message
    assert mock_client.return_value.__enter__.return_value.post.call_count == 3


@patch("app.services.voice_clone_service.httpx.Client")
def test_gnani_create_voice_timeout_mapped(mock_client):
    mock_client.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException("t")
    svc = GnaniVoiceCloneService(api_key="dummy-key")
    with pytest.raises(VoiceCloneError) as exc:
        svc.create_voice(b"x" * 2000, "sample.wav")
    assert exc.value.error_code == "VOICE_CLONE_TIMEOUT"
    assert exc.value.status_code == 504


@patch("app.services.voice_clone_service.httpx.Client")
def test_gnani_create_voice_success_parses_embedding(mock_client):
    mock_client.return_value.__enter__.return_value.post.return_value = _fake_response(
        200,
        {
            "success": True,
            "data": {
                "voice_clone_embedding": {
                    "embedding": "abc123",
                    "shape": [1, 768],
                    "dtype": "torch.bfloat16",
                }
            },
        },
    )
    svc = GnaniVoiceCloneService(api_key="dummy-key")
    ref = svc.create_voice(b"x" * 2000, "sample.wav")
    assert "abc123" in ref


def test_create_surfaces_provider_error_to_client(client, monkeypatch):
    """A VOICE_CLONE_FORBIDDEN from the provider becomes a clear HTTP error."""
    from app.api import voice_profiles as vp

    class _ForbiddenService:
        is_mock = False

        def create_voice(self, audio_bytes, filename="sample.wav"):
            raise VoiceCloneError(
                "Voice cloning is not enabled for this Gnani account (HTTP 403).",
                status_code=502,
                error_code="VOICE_CLONE_FORBIDDEN",
            )

    monkeypatch.setattr(vp, "get_voice_clone_service", lambda: _ForbiddenService())

    token = register_and_login(client, "t_err@example.com", "teacher")
    res = _create_profile(client, token)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "VOICE_CLONE_FORBIDDEN"
