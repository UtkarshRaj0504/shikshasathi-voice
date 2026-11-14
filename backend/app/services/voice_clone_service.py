"""
Voice clone service interface with Mock and Gnani implementations.
Generates speaker embeddings from reference audio samples for teacher voice cloning.
"""

import abc
import json
import logging
import uuid
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class VoiceCloneError(Exception):
    """Raised when voice clone operations fail."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class VoiceCloneService(abc.ABC):
    """Abstract base class for Voice Cloning services."""

    @property
    def is_mock(self) -> bool:
        return False

    @abc.abstractmethod
    def create_embedding(self, audio_bytes: bytes, filename: str = "sample.wav") -> str:
        """Upload reference audio (5-30s) and extract a speaker embedding."""
        pass

    @abc.abstractmethod
    def delete_embedding(self, voice_id: str) -> bool:
        """Delete or invalidate a remote speaker embedding (best-effort)."""
        pass


class MockVoiceCloneService(VoiceCloneService):
    """
    Mock Voice Clone service for testing and development.
    Generates deterministic mock speaker embeddings without network calls.
    """

    @property
    def is_mock(self) -> bool:
        return True

    def create_embedding(self, audio_bytes: bytes, filename: str = "sample.wav") -> str:
        if not audio_bytes or len(audio_bytes) < 100:
            raise VoiceCloneError("Reference audio is too short or empty.", status_code=400)
        return f"mock_vc_emb_{uuid.uuid4().hex[:12]}"

    def delete_embedding(self, voice_id: str) -> bool:
        return True


class GnaniVoiceCloneService(VoiceCloneService):
    """
    Real Gnani Voice Cloning integration (Vachana API).
    Uploads reference audio to POST https://api.vachana.ai/api/v1/tts/voice-clone/embeddings.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
    ):
        self.endpoint = endpoint or getattr(
            settings, "GNANI_VOICE_CLONE_ENDPOINT", "https://api.vachana.ai/api/v1/tts/voice-clone/embeddings"
        )
        self.api_key = api_key or getattr(settings, "GNANI_API_KEY", "")

    @property
    def is_mock(self) -> bool:
        return False

    def create_embedding(self, audio_bytes: bytes, filename: str = "sample.wav") -> str:
        if not self.api_key:
            raise VoiceCloneError("Gnani API key is not configured.", status_code=500)
        if not self.endpoint:
            raise VoiceCloneError("Gnani voice clone endpoint is not configured.", status_code=500)
        if not audio_bytes or len(audio_bytes) < 1000:
            raise VoiceCloneError("Reference audio is too short or empty. Please provide 5-30s of clear speech.", status_code=400)

        headers = {
            "X-API-Key-ID": self.api_key,
        }
        mime_type = "audio/wav" if filename.lower().endswith(".wav") else "audio/mpeg"
        files = {
            "audio_file": (filename, audio_bytes, mime_type),
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(self.endpoint, headers=headers, files=files)
        except httpx.TimeoutException:
            raise VoiceCloneError("Gnani voice clone embedding timed out.", status_code=504)
        except httpx.RequestError as exc:
            raise VoiceCloneError(f"Network error connecting to Gnani voice clone service: {exc}", status_code=502)

        if res.status_code == 401 or res.status_code == 403:
            raise VoiceCloneError("Gnani authentication failed. Check API key.", status_code=502)
        if res.status_code == 402:
            raise VoiceCloneError("Gnani voice clone quota exceeded.", status_code=502)
        if res.status_code == 429:
            raise VoiceCloneError("Gnani rate limit reached. Please try again in a minute.", status_code=429)
        if res.status_code >= 400:
            raise VoiceCloneError(f"Gnani voice clone embedding failed ({res.status_code}): {res.text[:200]}", status_code=502)

        try:
            data = res.json()
            # Can be returned as speaker_embedding or embedding or voice_id
            embedding = data.get("speaker_embedding") or data.get("embedding") or data.get("voice_id")
            if not embedding:
                # If data is a dict or string
                if isinstance(data, dict):
                    embedding = json.dumps(data)
                else:
                    embedding = str(data)
            return str(embedding)
        except Exception:
            text_resp = res.text.strip()
            if text_resp:
                return text_resp
            raise VoiceCloneError("Gnani voice clone returned empty embedding response.", status_code=502)

    def delete_embedding(self, voice_id: str) -> bool:
        # Gnani embeddings are stateless speaker embeddings or server-managed
        return True


def get_voice_clone_service() -> VoiceCloneService:
    provider = getattr(settings, "VOICE_CLONE_PROVIDER", "mock").lower()
    if provider == "gnani" and getattr(settings, "GNANI_API_KEY", ""):
        return GnaniVoiceCloneService()
    return MockVoiceCloneService()
