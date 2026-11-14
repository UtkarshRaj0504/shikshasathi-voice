"""
Voice cloning service interface with Mock and Gnani implementations.

Official contract (verified at https://docs.gnani.ai — Voice Cloning):

Step 1 — create a voice from reference audio (WAV/MP3, ~5-30 s of clear speech):
    POST https://api.vachana.ai/api/v1/tts/voice-clone/embeddings
    Header: X-API-Key-ID
    multipart/form-data field: audio_file
    -> {"success": true, "message": "...",
        "data": {"voice_clone_embedding": {"embedding": "<base64>", "shape": [1, 768],
                                           "dtype": "torch.bfloat16"}}}

Step 2 — synthesize with the cloned voice (REST, non-streaming — preferred):
    POST https://api.vachana.ai/api/v1/tts/inference
    Header: X-API-Key-ID
    Body: {"text": ..., "model": "vachana-vc-v1",
           "speaker_embedding": {"embedding": "...", "shape": [1, 768], "dtype": "torch.bfloat16"},
           "audio_config": {...}}
    -> raw audio bytes (audio/wav | audio/mpeg | audio/ogg)

There is no documented endpoint to delete a stored voice, so delete_voice() is a
best-effort no-op (see docs/DECISIONS.md).
"""

import abc
import json
import logging
import os
import sys
import uuid

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_VOICE_CLONE_ENDPOINT = "https://api.vachana.ai/api/v1/tts/voice-clone/embeddings"


class VoiceCloneError(Exception):
    """Raised when a voice clone operation fails. Never contains secrets."""

    def __init__(self, message: str, status_code: int = 502, error_code: str = "VOICE_CLONE_FAILED"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class VoiceCloneService(abc.ABC):
    """Abstract base class for voice cloning providers."""

    @property
    def is_mock(self) -> bool:
        return False

    @abc.abstractmethod
    def create_voice(self, audio_bytes: bytes, filename: str = "sample.wav") -> str:
        """Create a provider voice from reference audio; return a serialized embedding reference."""
        ...

    @abc.abstractmethod
    def synthesize_with_cloned_voice(self, embedding_ref: str, text: str, language: str = "en") -> bytes:
        """Synthesize text with a previously created cloned voice; return audio bytes."""
        ...

    @abc.abstractmethod
    def delete_voice(self, embedding_ref: str) -> bool:
        """Best-effort removal of the provider voice data."""
        ...


class MockVoiceCloneService(VoiceCloneService):
    """Deterministic, offline voice-clone service used in tests and without an API key."""

    @property
    def is_mock(self) -> bool:
        return True

    def create_voice(self, audio_bytes: bytes, filename: str = "sample.wav") -> str:
        if not audio_bytes or len(audio_bytes) < 100:
            raise VoiceCloneError("Reference audio is too short or empty.", status_code=400, error_code="VOICE_CLONE_BAD_AUDIO")
        # Mirrors the shape Gnani returns so downstream parsing is exercised for real.
        return json.dumps(
            {
                "voice_clone_embedding": {
                    "embedding": f"mock_embedding_{uuid.uuid4().hex[:12]}",
                    "shape": [1, 768],
                    "dtype": "torch.bfloat16",
                }
            }
        )

    def synthesize_with_cloned_voice(self, embedding_ref: str, text: str, language: str = "en") -> bytes:
        from app.services.tts_service import MockTTSService

        return MockTTSService().synthesize_speech(text, voice_id=embedding_ref, language=language, is_cloned=True)

    def delete_voice(self, embedding_ref: str) -> bool:
        return True


def _parse_embedding_response(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    inner = data.get("data")
    source = inner if isinstance(inner, dict) else data
    candidate = source.get("voice_clone_embedding") or source.get("speaker_embedding") or source.get("embedding")
    if isinstance(candidate, dict) and candidate.get("embedding"):
        return {
            "embedding": candidate["embedding"],
            "shape": candidate.get("shape") or [1, 768],
            "dtype": candidate.get("dtype") or "torch.bfloat16",
        }
    return None


class GnaniVoiceCloneService(VoiceCloneService):
    """Real Gnani Vachana voice cloning. Never silently falls back to a beep."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        tts_endpoint: str | None = None,
    ):
        self.endpoint = (
            endpoint or getattr(settings, "GNANI_VOICE_CLONE_ENDPOINT", "") or DEFAULT_VOICE_CLONE_ENDPOINT
        ).strip() or DEFAULT_VOICE_CLONE_ENDPOINT
        self.api_key = api_key if api_key is not None else getattr(settings, "GNANI_API_KEY", "")
        self.tts_endpoint = tts_endpoint  # None -> reuse the documented /tts/inference default

    @property
    def is_mock(self) -> bool:
        return False

    def _headers(self) -> dict:
        return {"X-API-Key-ID": self.api_key}

    def _gateway_error(self, res: httpx.Response) -> VoiceCloneError | None:
        """Map an auth/rate/credit failure (gateway `detail` envelope) to a clear error."""
        code = ""
        message = ""
        try:
            detail = res.json().get("detail")
            if isinstance(detail, dict):
                code = str(detail.get("error_code") or "")
                message = str(detail.get("message") or "")
        except Exception:
            pass
        if res.status_code == 401:
            return VoiceCloneError(
                "Voice cloning is not authorized (HTTP 401). Check the Gnani API key.",
                status_code=502,
                error_code="VOICE_CLONE_AUTH",
            )
        if res.status_code == 403:
            return VoiceCloneError(
                "Voice cloning is not enabled for this Gnani account (HTTP 403). "
                "Ask Gnani to enable the voice-cloning / vachana-vc-v1 scope for your API key.",
                status_code=502,
                error_code="VOICE_CLONE_FORBIDDEN",
            )
        if res.status_code == 402:
            return VoiceCloneError(
                "Voice cloning credit or quota limit reached (HTTP 402).",
                status_code=502,
                error_code="VOICE_CLONE_QUOTA",
            )
        if res.status_code == 429:
            return VoiceCloneError(
                f"Voice cloning rate limit exceeded (HTTP 429). {message}".strip(),
                status_code=429,
                error_code="VOICE_CLONE_RATE_LIMIT",
            )
        _ = code
        return None

    def create_voice(self, audio_bytes: bytes, filename: str = "sample.wav") -> str:
        if not (self.api_key or "").strip():
            raise VoiceCloneError(
                "Gnani API key is not configured. Set GNANI_API_KEY in the environment.",
                status_code=502,
                error_code="VOICE_CLONE_API_KEY_MISSING",
            )
        if not self.endpoint:
            raise VoiceCloneError(
                "Gnani voice clone endpoint is not configured.",
                status_code=502,
                error_code="VOICE_CLONE_NOT_CONFIGURED",
            )

        mime_type = "audio/wav" if (filename or "").lower().endswith(".wav") else "audio/mpeg"
        files = {"audio_file": (filename or "sample.wav", audio_bytes, mime_type)}

        try:
            with httpx.Client(timeout=60.0) as client:
                res = client.post(self.endpoint, headers=self._headers(), files=files)
        except httpx.TimeoutException:
            raise VoiceCloneError("Voice cloning timed out. Please try again.", status_code=504, error_code="VOICE_CLONE_TIMEOUT")
        except httpx.RequestError:
            raise VoiceCloneError("Network error connecting to the voice cloning service.", status_code=502, error_code="VOICE_CLONE_NETWORK")

        gw = self._gateway_error(res)
        if gw:
            raise gw
        if res.status_code in (400, 422):
            snippet = (res.text or "")[:200]
            raise VoiceCloneError(
                f"The reference audio was rejected ({res.status_code}). Please record 5-30 seconds "
                f"of clear speech in a quiet room. {snippet}".strip(),
                status_code=400,
                error_code="VOICE_CLONE_BAD_AUDIO",
            )
        if res.status_code >= 400:
            raise VoiceCloneError(
                f"Voice cloning failed (HTTP {res.status_code}).",
                status_code=502,
                error_code="VOICE_CLONE_PROVIDER_ERROR",
            )

        try:
            data = res.json()
        except Exception:
            raise VoiceCloneError("Voice cloning returned an unreadable response.", status_code=502, error_code="VOICE_CLONE_BAD_RESPONSE")

        embedding = _parse_embedding_response(data) if isinstance(data, dict) else None
        if not embedding:
            raise VoiceCloneError(
                "Voice cloning response did not contain a speaker embedding.",
                status_code=502,
                error_code="VOICE_CLONE_BAD_RESPONSE",
            )
        return json.dumps(embedding)

    def synthesize_with_cloned_voice(self, embedding_ref: str, text: str, language: str = "en") -> bytes:
        from app.services.tts_service import TTSError, GnaniTimbreTTSService

        service = GnaniTimbreTTSService(
            endpoint=self.tts_endpoint,
            api_key=self.api_key,
        )
        try:
            return service.synthesize_speech(text=text, voice_id=embedding_ref, language=language, is_cloned=True)
        except TTSError as e:
            raise VoiceCloneError(e.message, status_code=e.status_code, error_code=e.error_code)

    def delete_voice(self, embedding_ref: str) -> bool:
        # No documented provider endpoint deletes a stored voice; the embedding is our
        # only copy and it is discarded locally (see docs/DECISIONS.md).
        return True


def get_voice_clone_service() -> VoiceCloneService:
    """
    Select a voice clone implementation.

    - Tests (pytest / APP_ENV=test) always use Mock; no network calls.
    - VOICE_CLONE_PROVIDER=mock (default) -> Mock.
    - VOICE_CLONE_PROVIDER=gnani -> Gnani (errors clearly when the key is missing).
    - VOICE_CLONE_PROVIDER=auto -> Gnani when a key is present, otherwise Mock.
    """
    if "pytest" in sys.modules or os.getenv("APP_ENV") == "test" or settings.APP_ENV == "test":
        return MockVoiceCloneService()

    provider = (getattr(settings, "VOICE_CLONE_PROVIDER", "mock") or "mock").strip().lower()
    has_key = bool((getattr(settings, "GNANI_API_KEY", "") or "").strip())

    if provider == "mock":
        return MockVoiceCloneService()
    if provider == "gnani":
        return GnaniVoiceCloneService()
    if provider in ("auto", "") and has_key:
        return GnaniVoiceCloneService()
    return MockVoiceCloneService()
