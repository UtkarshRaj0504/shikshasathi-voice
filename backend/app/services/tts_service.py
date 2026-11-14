"""
TTS (Text-to-Speech) service interface with Mock and Gnani Timbre implementations.

Official REST contract (https://docs.gnani.ai/api/TTS/tts-inference):
  POST https://api.vachana.ai/api/v1/tts/inference
  Header X-API-Key-ID
  Body: text, voice, model, language, speed, audio_config
  Success: 200 with raw binary audio (audio/wav | audio/mpeg | audio/ogg)

Voice + model pairing (https://docs.gnani.ai/api/TTS/available-voices):
  timbre-v3.0 voices (Shivani, Lakshmi, ...) speak all 10 languages.
  timbre-v2.5 voices (Nalini, Kaveri, ...) are NOT interchangeable with v3.0.
  Using Shivani with timbre-v2.5 is rejected with HTTP 400.

Voice cloning (https://docs.gnani.ai/api/VC/vc-inference):
  Same inference URL, model vachana-vc-v1, speaker_embedding {embedding, shape, dtype}.
"""

import abc
import base64
import json
import logging
import math
import os
import struct
import sys

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Timbre v3.0: every voice speaks kn/hi/en (and the other 7 Indian languages).
# Lakshmi is documented as e-learning narration.
DEFAULT_TTS_MODEL = "timbre-v3.0"
DEFAULT_TTS_VOICE = "Lakshmi"
CLONE_TTS_MODEL = "vachana-vc-v1"
DEFAULT_SAMPLE_RATE = 24000


class TTSError(Exception):
    """Raised when text-to-speech synthesis fails. Never contains secrets."""

    def __init__(self, message: str, status_code: int = 502, error_code: str = "TTS_FAILED"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class TTSResult:
    """Audio bytes plus a browser-safe content type."""

    def __init__(self, audio_bytes: bytes, content_type: str = "audio/wav"):
        self.audio_bytes = audio_bytes
        self.content_type = content_type


class TTSService(abc.ABC):
    """Abstract base class for Text-to-Speech services."""

    @property
    def is_mock(self) -> bool:
        return False

    @abc.abstractmethod
    def synthesize_speech(
        self,
        text: str,
        voice_id: str | None = None,
        language: str = "en",
        is_cloned: bool = False,
    ) -> bytes:
        """Synthesize text into audio bytes (WAV/MP3)."""
        pass

    def synthesize(self, *args, **kwargs) -> TTSResult:
        audio = self.synthesize_speech(*args, **kwargs)
        return TTSResult(audio, detect_audio_content_type(audio))


class MockTTSService(TTSService):
    """
    Mock TTS that generates a valid 16 kHz mono WAV tone.
    Used only when TTS_PROVIDER=mock (or auto with no API key). Clearly labelled in the UI.
    """

    @property
    def is_mock(self) -> bool:
        return True

    def synthesize_speech(
        self,
        text: str,
        voice_id: str | None = None,
        language: str = "en",
        is_cloned: bool = False,
    ) -> bytes:
        freq = 320.0 if is_cloned else 440.0
        duration_s = max(0.3, min(2.0, len(text) * 0.015))
        sample_rate = 16000
        num_samples = int(duration_s * sample_rate)
        raw_data = bytearray()
        for i in range(num_samples):
            envelope = min(1.0, (i / 800.0), ((num_samples - i) / 800.0))
            envelope = max(0.0, envelope)
            val = int(32767 * 0.15 * envelope * math.sin(2 * math.pi * freq * (i / sample_rate)))
            raw_data.extend(struct.pack("<h", val))

        header = bytearray()
        header.extend(b"RIFF")
        header.extend(struct.pack("<I", 36 + len(raw_data)))
        header.extend(b"WAVEfmt ")
        header.extend(struct.pack("<I", 16))
        header.extend(struct.pack("<H", 1))
        header.extend(struct.pack("<H", 1))
        header.extend(struct.pack("<I", sample_rate))
        header.extend(struct.pack("<I", sample_rate * 2))
        header.extend(struct.pack("<H", 2))
        header.extend(struct.pack("<H", 16))
        header.extend(b"data")
        header.extend(struct.pack("<I", len(raw_data)))
        return bytes(header + raw_data)


def detect_audio_content_type(body: bytes) -> str:
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WAVE":
        return "audio/wav"
    if body[:3] == b"ID3" or (len(body) >= 2 and body[0] == 0xFF and body[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if body[:4] == b"OggS":
        return "audio/ogg"
    return "audio/wav"


def _sanitize_error_text(text: str, api_key: str = "") -> str:
    cleaned = (text or "").replace("\n", " ")[:240]
    if api_key:
        cleaned = cleaned.replace(api_key, "[redacted]")
    return cleaned


def parse_speaker_embedding(voice_id: str) -> dict:
    """Turn a stored embedding (JSON object or raw string) into the Gnani speaker_embedding object."""
    raw = (voice_id or "").strip()
    if not raw:
        raise TTSError("Cloned voice is missing a speaker embedding.", status_code=400, error_code="MISSING_EMBEDDING")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {"embedding": raw, "shape": [1, 768], "dtype": "torch.bfloat16"}

    if isinstance(obj, dict):
        inner = obj.get("voice_clone_embedding") or obj.get("data") or obj
        if isinstance(inner, dict) and isinstance(inner.get("voice_clone_embedding"), dict):
            inner = inner["voice_clone_embedding"]
        if isinstance(inner, dict) and inner.get("embedding"):
            return {
                "embedding": inner["embedding"],
                "shape": inner.get("shape") or [1, 768],
                "dtype": inner.get("dtype") or "torch.bfloat16",
            }
    return {"embedding": raw, "shape": [1, 768], "dtype": "torch.bfloat16"}


def extract_audio_from_response(res: httpx.Response, api_key: str = "") -> bytes:
    """Return playable audio bytes from a Gnani TTS HTTP response."""
    content_type = (res.headers.get("content-type") or "").lower()
    body = res.content or b""

    if "application/json" in content_type:
        try:
            data = res.json()
        except Exception as e:
            raise TTSError(f"Failed to parse Gnani TTS JSON response: {e}", status_code=502, error_code="BAD_AUDIO")
        b64_audio = (
            data.get("audioContent")
            or data.get("audio")
            or data.get("audio_content")
            or (data.get("data") or {}).get("audioContent")
            or (data.get("data") or {}).get("audio")
        )
        if not b64_audio:
            raise TTSError("Gnani TTS response missing audio payload.", status_code=502, error_code="BAD_AUDIO")
        try:
            body = base64.b64decode(b64_audio)
        except Exception:
            raise TTSError("Gnani TTS returned undecodable audio payload.", status_code=502, error_code="BAD_AUDIO")

    if len(body) < 44:
        raise TTSError("Gnani TTS returned invalid or empty audio data.", status_code=502, error_code="BAD_AUDIO")

    # Raw PCM without a container cannot be decoded by HTML <audio>; wrap as WAV.
    if body[:4] != b"RIFF" and body[:3] != b"ID3" and body[:4] != b"OggS" and not (
        len(body) >= 2 and body[0] == 0xFF and body[1] & 0xE0 == 0xE0
    ):
        body = _wrap_pcm_as_wav(body, DEFAULT_SAMPLE_RATE)

    _ = api_key  # unused; kept so callers never interpolate the key elsewhere
    return body


def _wrap_pcm_as_wav(pcm: bytes, sample_rate: int) -> bytes:
    header = bytearray()
    header.extend(b"RIFF")
    header.extend(struct.pack("<I", 36 + len(pcm)))
    header.extend(b"WAVEfmt ")
    header.extend(struct.pack("<I", 16))
    header.extend(struct.pack("<H", 1))
    header.extend(struct.pack("<H", 1))
    header.extend(struct.pack("<I", sample_rate))
    header.extend(struct.pack("<I", sample_rate * 2))
    header.extend(struct.pack("<H", 2))
    header.extend(struct.pack("<H", 16))
    header.extend(b"data")
    header.extend(struct.pack("<I", len(pcm)))
    return bytes(header + pcm)


class GnaniTimbreTTSService(TTSService):
    """
    Real Gnani Timbre & voice-cloned TTS (Vachana API).
    Never silently falls back to a beep: raises TTSError on failure.
    """

    DEFAULT_VOICE = DEFAULT_TTS_VOICE
    MODEL_STANDARD = DEFAULT_TTS_MODEL
    MODEL_VOICE_CLONE = CLONE_TTS_MODEL

    LANGUAGE_MAP = {
        "en": "en-IN",
        "hi": "hi-IN",
        "kn": "kn-IN",
        "ta": "ta-IN",
        "te": "te-IN",
        "mr": "mr-IN",
        "bn": "bn-IN",
        "gu": "gu-IN",
        "pa": "pa-IN",
        "ml": "ml-IN",
        "auto": "auto",
        "indic-auto": "auto",
    }

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        default_voice: str | None = None,
    ):
        # Endpoint: use provided, then settings, then hardcoded default
        self.endpoint = (endpoint or getattr(settings, "GNANI_TIMBRE_ENDPOINT", "") or "https://api.vachana.ai/api/v1/tts/inference").strip() or "https://api.vachana.ai/api/v1/tts/inference"
        self.api_key = api_key if api_key is not None else getattr(settings, "GNANI_API_KEY", "")
        self.model = model or getattr(settings, "GNANI_TTS_MODEL", DEFAULT_TTS_MODEL)
        self.default_voice = default_voice or getattr(settings, "GNANI_TTS_VOICE", DEFAULT_TTS_VOICE)

    @property
    def is_mock(self) -> bool:
        return False

    def _normalize_language(self, lang: str) -> str:
        clean = (lang or "en").strip().lower()
        if clean in self.LANGUAGE_MAP:
            return self.LANGUAGE_MAP[clean]
        if "-" in clean:
            return clean
        return "en-IN"

    def synthesize_speech(
        self,
        text: str,
        voice_id: str | None = None,
        language: str = "en",
        is_cloned: bool = False,
    ) -> bytes:
        if not (self.api_key or "").strip():
            raise TTSError(
                "Gnani TTS API key is not configured. Set GNANI_API_KEY in environment.",
                status_code=500,
                error_code="TTS_API_KEY_MISSING",
            )
        if not text or not text.strip():
            raise TTSError("Cannot synthesize empty text.", status_code=400, error_code="EMPTY_TEXT")

        lang_code = self._normalize_language(language)
        headers = {
            "X-API-Key-ID": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/wav, audio/mpeg, application/octet-stream, application/json",
        }
        audio_config = {
            "encoding": "linear_pcm",
            "container": "wav",
            "num_channels": 1,
            "sample_rate": DEFAULT_SAMPLE_RATE,
            "sample_width": 2,
        }

        if is_cloned:
            payload = {
                "text": text.strip(),
                "model": self.MODEL_VOICE_CLONE,
                "speaker_embedding": parse_speaker_embedding(voice_id or ""),
                "language": lang_code,
                "speed": 1.0,
                "audio_config": audio_config,
            }
        else:
            payload = {
                "text": text.strip(),
                "model": self.model,
                "voice": self.default_voice,
                "language": lang_code,
                "speed": 1.0,
                "audio_config": audio_config,
            }

        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.post(self.endpoint, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise TTSError("Gnani TTS service timed out. Please try again.", status_code=504, error_code="TTS_TIMEOUT")
        except httpx.RequestError:
            raise TTSError("Network error connecting to Gnani TTS service.", status_code=502, error_code="TTS_NETWORK")

        if res.status_code in (401, 403):
            raise TTSError(
                "Gnani TTS authentication failed. Check API key configuration.",
                status_code=502,
                error_code="TTS_AUTH",
            )
        if res.status_code == 402:
            raise TTSError("Gnani TTS credit or quota limit reached.", status_code=502, error_code="TTS_QUOTA")
        if res.status_code == 429:
            raise TTSError(
                "Gnani TTS rate limit exceeded. Please try again in a minute.",
                status_code=429,
                error_code="TTS_RATE_LIMIT",
            )
        if res.status_code >= 400:
            snippet = _sanitize_error_text(res.text, self.api_key)
            raise TTSError(
                f"Gnani TTS request failed (HTTP {res.status_code}): {snippet}",
                status_code=502,
                error_code="TTS_PROVIDER_ERROR",
            )

        return extract_audio_from_response(res, self.api_key)


def get_tts_service() -> TTSService:
    """
    Select TTS implementation.
    - Tests always use Mock.
    - TTS_PROVIDER=mock -> Mock (labelled in UI).
    - TTS_PROVIDER=gnani -> Gnani (errors if the key is missing; never beeps).
    - TTS_PROVIDER=auto (default) -> Gnani when a key is present, otherwise Mock.
    """
    if "pytest" in sys.modules or os.getenv("APP_ENV") == "test" or settings.APP_ENV == "test":
        return MockTTSService()

    provider = (getattr(settings, "TTS_PROVIDER", "auto") or "auto").strip().lower()
    has_key = bool((getattr(settings, "GNANI_API_KEY", "") or "").strip())

    if provider == "mock":
        return MockTTSService()
    if provider == "gnani":
        return GnaniTimbreTTSService()
    if provider in ("auto", "") and has_key:
        return GnaniTimbreTTSService()
    return MockTTSService()
