"""
Unit and integration tests for TTS (Text-to-Speech) service and endpoint.
Verifies Mock and Gnani Timbre providers, error conditions, status codes, and non-silent fallback.
"""

import base64
import json
import pytest
import httpx
from unittest.mock import patch, MagicMock

def _student_token(client):
    client.post(
        "/auth/register",
        json={"email": "tts_student@example.com", "name": "TTS Student", "password": "password123", "role": "student"},
    )
    res = client.post("/auth/login", json={"email": "tts_student@example.com", "password": "password123"})
    return res.json()["access_token"]


from app.services.tts_service import (
    MockTTSService,
    GnaniTimbreTTSService,
    TTSError,
    get_tts_service,
)


def test_mock_tts_service_generates_valid_wav():
    service = MockTTSService()
    assert service.is_mock is True
    audio = service.synthesize_speech("Hello, student! Welcome to photosynthesis.")
    assert isinstance(audio, bytes)
    assert len(audio) > 44
    assert audio[:4] == b"RIFF"
    assert audio[8:12] == b"WAVE"


def test_gnani_timbre_tts_success_binary():
    dummy_wav = b"RIFF" + b"\x00" * 36 + b"WAVEfmt " + b"\x00" * 20 + b"data" + b"\x00" * 100
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )
    assert service.is_mock is False

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "audio/wav"}
    mock_resp.content = dummy_wav

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        result = service.synthesize_speech("Photosynthesis is how plants make food.", language="hi")
        assert result == dummy_wav

        # Verify request parameters sent to Gnani
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["headers"]["X-API-Key-ID"] == "test-gnani-key"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        payload = kwargs["json"]
        assert payload["text"] == "Photosynthesis is how plants make food."
        assert payload["language"] == "hi-IN"
        assert payload["model"] == "timbre-v3.0"
        assert payload["voice"] == "Lakshmi"
        assert payload["audio_config"]["container"] == "wav"
        assert payload["audio_config"]["sample_rate"] == 24000


def test_gnani_timbre_tts_success_json_base64():
    dummy_wav = b"RIFF" + b"\x00" * 40 + b"WAVEfmt " + b"\x00" * 50
    b64_audio = base64.b64encode(dummy_wav).decode("ascii")

    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.content = b'{"audioContent": "' + b64_audio.encode("ascii") + b'"}'
    mock_resp.json.return_value = {"audioContent": b64_audio}

    with patch("httpx.Client.post", return_value=mock_resp):
        result = service.synthesize_speech("Hello from base64 audio")
        assert result == dummy_wav


def test_gnani_cloned_tts_sends_speaker_embedding_object():
    dummy_wav = b"RIFF" + b"\x00" * 36 + b"WAVEfmt " + b"\x00" * 20 + b"data" + b"\x00" * 100
    embedding = json.dumps({"embedding": "abc", "shape": [1, 768], "dtype": "torch.bfloat16"})
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "audio/wav"}
    mock_resp.content = dummy_wav

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        service.synthesize_speech("Hello", voice_id=embedding, language="kn", is_cloned=True)
        payload = mock_post.call_args.kwargs["json"]
        assert payload["model"] == "vachana-vc-v1"
        assert payload["speaker_embedding"]["embedding"] == "abc"
        assert payload["speaker_embedding"]["shape"] == [1, 768]
        assert payload["language"] == "kn-IN"


def test_gnani_timbre_tts_401_403_authentication_error():
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="invalid-gnani-key",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized key"

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(TTSError) as exc_info:
            service.synthesize_speech("Testing authentication failure")
        assert exc_info.value.status_code == 502
        assert "authentication failed" in exc_info.value.message.lower()
        # Verify no secret is leaked in message
        assert "invalid-gnani-key" not in exc_info.value.message


def test_gnani_timbre_tts_403_scope_error():
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "SCOPE_NOT_ALLOWED"

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(TTSError) as exc_info:
            service.synthesize_speech("Testing scope failure")
        assert exc_info.value.status_code == 502
        assert "authentication failed" in exc_info.value.message.lower()


def test_gnani_timbre_tts_402_quota_error():
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 402
    mock_resp.text = "Payment Required: Out of credits"

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(TTSError) as exc_info:
            service.synthesize_speech("Testing payment required")
        assert exc_info.value.status_code == 502
        assert "quota limit" in exc_info.value.message.lower()


def test_gnani_timbre_tts_429_rate_limit():
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Rate limit exceeded"

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(TTSError) as exc_info:
            service.synthesize_speech("Testing rate limit")
        assert exc_info.value.status_code == 429
        assert "rate limit exceeded" in exc_info.value.message.lower()
        assert "try again in a minute" in exc_info.value.message.lower()


def test_gnani_timbre_tts_timeout():
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timed out")):
        with pytest.raises(TTSError) as exc_info:
            service.synthesize_speech("Testing timeout")
        assert exc_info.value.status_code == 504
        assert "timed out" in exc_info.value.message.lower()


def test_gnani_timbre_tts_corrupt_bad_audio():
    service = GnaniTimbreTTSService(
        endpoint="https://api.vachana.ai/api/v1/tts/inference",
        api_key="test-gnani-key",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "audio/wav"}
    mock_resp.content = b"SHORT"  # only 5 bytes, invalid WAV

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(TTSError) as exc_info:
            service.synthesize_speech("Testing corrupt audio")
        assert exc_info.value.status_code == 502
        assert "invalid or empty audio" in exc_info.value.message.lower()


def test_speak_endpoint_mock_voice_indicates_is_mock(client):
    token = _student_token(client)
    res = client.post(
        "/tts/speak",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "This is mock audio test", "language": "en"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["content_type"] == "audio/wav"
    assert data["voice_used"] == "default"
    assert data["is_mock"] is True
    assert data["audio_base64"] is not None


def test_speak_endpoint_real_tts_failure_does_not_beep(client):
    """When the active TTS provider fails, /tts/speak must return an explicit HTTP error, not a beep."""
    failing_service = MagicMock()
    failing_service.is_mock = False
    failing_service.synthesize_speech.side_effect = TTSError(
        "Gnani TTS rate limit exceeded. Please try again in a minute.",
        status_code=429,
    )

    with patch("app.api.tts.get_tts_service", return_value=failing_service):
        res = client.post(
            "/tts/speak",
            headers={"Authorization": f"Bearer {_student_token(client)}"},
            json={"text": "Should not silently beep on error", "language": "en"},
        )
        assert res.status_code == 429
        detail = res.json()["detail"]
        message = detail["message"] if isinstance(detail, dict) else detail
        assert "rate limit exceeded" in message.lower()


def test_gnani_provider_without_key_does_not_beep():
    service = GnaniTimbreTTSService(endpoint="https://api.vachana.ai/api/v1/tts/inference", api_key="")
    with pytest.raises(TTSError) as exc_info:
        service.synthesize_speech("Should fail loudly")
    # A missing API key is a distinct, specific config error (never a silent beep,
    # and never conflated with the endpoint being unset).
    assert exc_info.value.error_code == "TTS_API_KEY_MISSING"
    assert exc_info.value.status_code == 500


def test_gnani_tts_endpoint_defaults_to_documented_url_when_env_unset():
    """BUG 3 regression: with no env override the endpoint must be the documented URL."""
    service = GnaniTimbreTTSService(api_key="test-key", endpoint="")
    with patch("app.services.tts_service.settings.GNANI_TIMBRE_ENDPOINT", ""):
        service = GnaniTimbreTTSService(api_key="test-key")
    assert service.endpoint == "https://api.vachana.ai/api/v1/tts/inference"
    # Documented defaults for model + voice (timbre-v3.0 / Lakshmi).
    assert service.model == "timbre-v3.0"
    assert service.default_voice == "Lakshmi"


def test_gnani_tts_endpoint_override_via_env():
    """An explicit env override must still be honoured."""
    service = GnaniTimbreTTSService(endpoint="https://example.test/custom/tts", api_key="test-key")
    assert service.endpoint == "https://example.test/custom/tts"

