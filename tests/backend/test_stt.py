"""
Tests for Speech-to-Text (STT) transcription endpoint and services.
"""

import io
import pytest
from unittest.mock import AsyncMock, patch
import httpx

from app.services.stt_service import (
    GnaniPrismaSTTService,
    get_stt_service,
    normalize_language_code,
)


def register_and_login(client, email, name, role):
    client.post("/auth/register", json={
        "email": email,
        "name": name,
        "password": "password123",
        "role": role
    })
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    return res.json()["access_token"]


def test_stt_transcribe_student_success(client):
    student_token = register_and_login(client, "student_stt@example.com", "Student STT", "student")

    audio_bytes = b"RIFF....WAVEfmt ....data...."
    response = client.post(
        "/stt/transcribe",
        files={"audio": ("test_audio.webm", io.BytesIO(audio_bytes), "audio/webm")},
        data={"language_code": "en"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "transcript" in data
    assert "language" in data
    # The response reports the normalized (BCP-47) / detected language, not the raw input.
    assert data["language"] == "en-IN"


def test_stt_transcribe_english_is_never_forced_to_hindi(client):
    """BUG 2 regression: asking in English must not come back as a Hindi transcript."""
    student_token = register_and_login(client, "student_en@example.com", "Student EN", "student")

    response = client.post(
        "/stt/transcribe",
        files={"audio": ("audio.webm", io.BytesIO(b"english speech"), "audio/webm")},
        data={"language_code": "en"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "en-IN"
    # English speech returns an English (Latin-script) transcript, not Devanagari.
    assert "photosynthesis" in data["transcript"].lower()
    assert not any("\u0900" <= ch <= "\u097f" for ch in data["transcript"])


@pytest.mark.parametrize(
    "sent,expected",
    [
        ("en", "en-IN"),
        ("en-IN", "en-IN"),
        ("en-US", "en-IN"),
        ("hi", "hi-IN"),
        ("kn", "kn-IN"),
        ("ta", "ta-IN"),
        # "auto"/unknown must use the documented auto-detect value, never Hindi.
        ("auto", "indic-auto"),
        ("indic-auto", "indic-auto"),
        ("unknown_xyz", "indic-auto"),
        ("", "indic-auto"),
        # as-IN is unsupported by prisma-v3.0, so it is routed through auto-detect.
        ("as", "indic-auto"),
        ("as-IN", "indic-auto"),
    ],
)
def test_stt_language_code_mapping(client, sent, expected):
    student_token = register_and_login(
        client, f"student_map_{sent or 'empty'}@example.com".replace("+", ""), "Student Map", "student"
    )

    response = client.post(
        "/stt/transcribe",
        files={"audio": ("audio.webm", io.BytesIO(b"speech"), "audio/webm")},
        data={"language_code": sent},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 200
    assert response.json()["language"] == expected


def test_stt_transcript_preserves_native_script(client):
    """Kannada and Hindi stay in native script; no transliteration."""
    student_token = register_and_login(client, "student_native@example.com", "Student Native", "student")

    resp_kn = client.post(
        "/stt/transcribe",
        files={"audio": ("audio.webm", io.BytesIO(b"kannada"), "audio/webm")},
        data={"language_code": "kn"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert resp_kn.status_code == 200
    assert any("\u0c80" <= ch <= "\u0cff" for ch in resp_kn.json()["transcript"])

    resp_hi = client.post(
        "/stt/transcribe",
        files={"audio": ("audio.webm", io.BytesIO(b"hindi"), "audio/webm")},
        data={"language_code": "hi"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert resp_hi.status_code == 200
    assert any("\u0900" <= ch <= "\u097f" for ch in resp_hi.json()["transcript"])


def test_stt_transcribe_bad_file_type(client):
    student_token = register_and_login(client, "student_bad@example.com", "Student Bad", "student")

    response = client.post(
        "/stt/transcribe",
        files={"audio": ("doc.pdf", io.BytesIO(b"%PDF..."), "application/pdf")},
        data={"language_code": "auto"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 400
    assert "Invalid audio file type" in response.json()["detail"]


def test_stt_transcribe_oversized(client):
    student_token = register_and_login(client, "student_big@example.com", "Student Big", "student")

    # 11MB file (> 10MB limit)
    large_audio = b"a" * (11 * 1024 * 1024)
    response = client.post(
        "/stt/transcribe",
        files={"audio": ("large.webm", io.BytesIO(large_audio), "audio/webm")},
        data={"language_code": "auto"},
        headers={"Authorization": f"Bearer {student_token}"}
    )
    assert response.status_code == 400
    assert "exceeds the 10MB size limit" in response.json()["detail"]


def test_stt_transcribe_teacher_forbidden(client):
    teacher_token = register_and_login(client, "teacher_stt@example.com", "Teacher STT", "teacher")

    response = client.post(
        "/stt/transcribe",
        files={"audio": ("audio.webm", io.BytesIO(b"audio"), "audio/webm")},
        data={"language_code": "en"},
        headers={"Authorization": f"Bearer {teacher_token}"}
    )
    assert response.status_code == 403


def test_stt_transcribe_unauthenticated(client):
    response = client.post(
        "/stt/transcribe",
        files={"audio": ("audio.webm", io.BytesIO(b"audio"), "audio/webm")},
        data={"language_code": "en"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_gnani_service_success():
    service = GnaniPrismaSTTService()

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {"transcript": "Hello from Gnani", "language": "kn"}

    with patch("app.services.stt_service.settings.GNANI_API_KEY", "test-api-key"), \
         patch("httpx.AsyncClient.post", return_value=mock_response):
        res = await service.transcribe(b"audio_data", "kn", "audio.webm")
        assert res["transcript"] == "Hello from Gnani"
        assert res["language"] == "kn"


@pytest.mark.asyncio
async def test_gnani_service_errors():
    service = GnaniPrismaSTTService()

    # 401 Unauthorized
    resp_401 = AsyncMock()
    resp_401.status_code = 401
    with patch("app.services.stt_service.settings.GNANI_API_KEY", "bad-key"), \
         patch("httpx.AsyncClient.post", return_value=resp_401):
        with pytest.raises(Exception) as exc_info:
            await service.transcribe(b"audio", "en", "audio.webm")
        assert "401" in str(exc_info.value)

    # 402 Payment Required
    resp_402 = AsyncMock()
    resp_402.status_code = 402
    with patch("app.services.stt_service.settings.GNANI_API_KEY", "key"), \
         patch("httpx.AsyncClient.post", return_value=resp_402):
        with pytest.raises(Exception) as exc_info:
            await service.transcribe(b"audio", "en", "audio.webm")
        assert "402" in str(exc_info.value)

    # 429 Too Many Requests is retried with backoff before it is surfaced.
    resp_429 = AsyncMock()
    resp_429.status_code = 429
    resp_429.headers = {}
    with patch("app.services.stt_service.settings.GNANI_API_KEY", "key"), \
         patch("app.services.stt_service.stt_retry_delay_seconds", return_value=0.0), \
         patch("httpx.AsyncClient.post", return_value=resp_429) as mock_post:
        with pytest.raises(Exception) as exc_info:
            await service.transcribe(b"audio", "en", "audio.webm")
        assert "429" in str(exc_info.value)
        assert mock_post.call_count == 3

    # Timeout
    with patch("app.services.stt_service.settings.GNANI_API_KEY", "key"), \
         patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Timeout")):
        with pytest.raises(Exception) as exc_info:
            await service.transcribe(b"audio", "en", "audio.webm")
        assert "timed out" in str(exc_info.value)


def test_normalize_language_code():
    assert normalize_language_code("auto") == "indic-auto"
    assert normalize_language_code("indic-auto") == "indic-auto"
    assert normalize_language_code("en") == "en-IN"
    assert normalize_language_code("hi") == "hi-IN"
    assert normalize_language_code("kn") == "kn-IN"
    assert normalize_language_code("ta") == "ta-IN"
    assert normalize_language_code("unknown_xyz") == "indic-auto"


@pytest.mark.asyncio
async def test_gnani_service_empty_transcript_handling():
    service = GnaniPrismaSTTService()

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = lambda: {
        "success": True,
        "request_id": "test-req",
        "transcript": "",
        "detected_language_code": "hi-IN"
    }

    with patch("app.services.stt_service.settings.GNANI_API_KEY", "test-api-key"), \
         patch("httpx.AsyncClient.post", return_value=mock_response):
        res = await service.transcribe(b"audio_bytes", "hi", "audio.wav")
        # Must be empty string, not stringified dict representation
        assert res["transcript"] == ""
        assert res["language"] == "hi-IN"

