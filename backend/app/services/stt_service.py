"""
Speech-to-Text (STT) service abstraction with Mock and Gnani Prisma implementations.
"""

from abc import ABC, abstractmethod
import io
import logging
import os
from typing import Dict, Any
import httpx
from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

# Normalize input language code to the BCP-47 codes Gnani Prisma v3.0 expects.
#
# Verified against https://docs.gnani.ai/api/STT/speech-to-text:
#   - language_code is a BCP-47 code (region part uppercase, e.g. "en-IN").
#   - Prisma v3.0 accepts one language, or "indic-auto" for documented
#     auto-detection across Indian languages, or a comma-separated list of 1-4.
#   - Lowercase region codes ("en-in") and unsupported codes return HTTP 400
#     INVALID_LANGUAGE_CODE. as-IN is NOT supported by prisma-v3.0
#     (MODEL_UNSUPPORTED_LANGUAGE), so it is routed through auto-detect instead.
LANGUAGE_CODE_MAP = {
    "auto": "indic-auto",
    "indic-auto": "indic-auto",
    "kn": "kn-IN",
    "kn-in": "kn-IN",
    "hi": "hi-IN",
    "hi-in": "hi-IN",
    "en": "en-IN",
    "en-in": "en-IN",
    "en-us": "en-IN",
    "ta": "ta-IN",
    "ta-in": "ta-IN",
    "te": "te-IN",
    "te-in": "te-IN",
    "mr": "mr-IN",
    "mr-in": "mr-IN",
    "gu": "gu-IN",
    "gu-in": "gu-IN",
    "bn": "bn-IN",
    "bn-in": "bn-IN",
    "ml": "ml-IN",
    "ml-in": "ml-IN",
    "pa": "pa-IN",
    "pa-in": "pa-IN",
    # as-IN is a valid Gnani code but prisma-v3.0 does not cover it; auto-detect.
    "as": "indic-auto",
    "as-in": "indic-auto",
}

# The documented auto-detect value for Prisma v3.0.
DEFAULT_LANGUAGE_CODE = "indic-auto"


def normalize_language_code(language_code: str) -> str:
    """Normalize an input language code to a Gnani Prisma v3.0 BCP-47 code.

    "auto" maps to the documented auto-detect behaviour ("indic-auto"), which is
    also the fallback for empty/unknown input. It never silently maps to a
    specific language such as Hindi, so speaking English is never forced to Hindi.
    """
    cleaned = (language_code or DEFAULT_LANGUAGE_CODE).strip().lower()
    return LANGUAGE_CODE_MAP.get(cleaned, DEFAULT_LANGUAGE_CODE)


def convert_audio_to_wav(audio_bytes: bytes, target_sample_rate: int = 16000) -> bytes:
    """
    Convert any audio format (webm, mp3, ogg, m4a, wav, flac, etc.) to standard 16kHz mono WAV (PCM 16-bit).
    This ensures compatibility with Gnani Prisma STT which rejects webm and performs best with 16kHz mono WAV.
    """
    try:
        import av
        input_buffer = io.BytesIO(audio_bytes)
        output_buffer = io.BytesIO()

        with av.open(input_buffer) as in_container:
            if not in_container.streams.audio:
                return audio_bytes
            in_stream = in_container.streams.audio[0]
            with av.open(output_buffer, mode="w", format="wav") as out_container:
                out_stream = out_container.add_stream("pcm_s16le", rate=target_sample_rate)
                out_stream.layout = "mono"
                resampler = av.AudioResampler(
                    format="s16",
                    layout="mono",
                    rate=target_sample_rate
                )

                for frame in in_container.decode(in_stream):
                    for resampled_frame in resampler.resample(frame):
                        for packet in out_stream.encode(resampled_frame):
                            out_container.mux(packet)

                # Flush encoder
                for packet in out_stream.encode(None):
                    out_container.mux(packet)

        converted = output_buffer.getvalue()
        if len(converted) > 44:  # Valid non-empty WAV header
            return converted
    except Exception as exc:
        logger.warning(f"Audio conversion with av failed, proceeding with original audio: {exc}")

    return audio_bytes


class STTService(ABC):
    """Abstract base class for Speech-to-Text services."""

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, language_code: str, filename: str) -> dict:
        """Transcribe audio bytes to text and return {transcript, language}."""
        pass


class MockSTTService(STTService):
    """Mock STT service for local development and testing without live API calls."""

    async def transcribe(self, audio_bytes: bytes, language_code: str, filename: str) -> dict:
        transcripts = {
            "kn": "ಫೋಟೋಸಿಂಥೆಸಿಸ್ ಎಂದರೇನು ಮತ್ತು ಸಸ್ಯಗಳು ಆಹಾರವನ್ನು ಹೇಗೆ ತಯಾರಿಸುತ್ತವೆ?",
            "kn-IN": "ಫೋಟೋಸಿಂಥೆಸಿಸ್ ಎಂದರೇನು ಮತ್ತು ಸಸ್ಯಗಳು ಆಹಾರವನ್ನು ಹೇಗೆ ತಯಾರಿಸುತ್ತವೆ?",
            "hi": "प्रकाश संश्लेषण क्या है और पौधे अपना भोजन कैसे बनाते हैं?",
            "hi-IN": "प्रकाश संश्लेषण क्या है और पौधे अपना भोजन कैसे बनाते हैं?",
            "en": "What is photosynthesis and how do plants make their food?",
            "en-IN": "What is photosynthesis and how do plants make their food?",
            "auto": "What is photosynthesis and how do plants make their food?",
            "indic-auto": "What is photosynthesis and how do plants make their food?",
        }
        # Report the normalized (BCP-47) / detected language, mirroring the real
        # provider's ``detected_language_code`` field. Never echo the raw input
        # back, so the transcript response always shows a concrete language code
        # instead of a stale/invalid one.
        normalized = normalize_language_code(language_code)
        text = transcripts.get(normalized, transcripts.get(language_code, transcripts["en-IN"]))
        return {"transcript": text, "language": normalized}


class GnaniPrismaSTTService(STTService):
    """Gnani Prisma STT v3 REST API integration."""

    async def transcribe(self, audio_bytes: bytes, language_code: str, filename: str) -> dict:
        endpoint = settings.GNANI_PRISMA_ENDPOINT or "https://api.vachana.ai/stt/v3"
        api_key = settings.GNANI_API_KEY

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gnani API key is not configured in backend environment."
            )

        resolved_lang = normalize_language_code(language_code)

        # Transcode audio to 16kHz mono WAV for maximum compatibility with Gnani
        wav_bytes = convert_audio_to_wav(audio_bytes, target_sample_rate=16000)

        headers = {
            "X-API-Key-ID": api_key
        }
        files = {
            "audio_file": ("audio.wav", wav_bytes, "audio/wav")
        }
        data = {
            "model": "prisma-v3.0",
            "language_code": resolved_lang
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(endpoint, headers=headers, files=files, data=data)

                if response.status_code == 401:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Gnani API authentication failed (401: Invalid API Key)"
                    )
                elif response.status_code == 402:
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail="Gnani API payment required / quota exceeded (402)"
                    )
                elif response.status_code == 429:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Gnani API rate limit exceeded (429)"
                    )
                elif response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Gnani API error ({response.status_code}): {response.text}"
                    )

                res_data = response.json()
                transcript = ""
                if isinstance(res_data, dict):
                    if "transcript" in res_data and isinstance(res_data["transcript"], str):
                        transcript = res_data["transcript"]
                    elif "text" in res_data and isinstance(res_data["text"], str):
                        transcript = res_data["text"]
                    elif isinstance(res_data.get("data"), dict) and "transcript" in res_data["data"]:
                        transcript = res_data["data"]["transcript"] or ""
                    elif isinstance(res_data.get("result"), dict) and "transcript" in res_data["result"]:
                        transcript = res_data["result"]["transcript"] or ""
                    elif isinstance(res_data.get("hypotheses"), list) and res_data["hypotheses"]:
                        transcript = res_data["hypotheses"][0].get("transcript", "") or ""

                detected_lang = (
                    res_data.get("detected_language_code")
                    or res_data.get("language")
                    or res_data.get("lang")
                    or resolved_lang
                )
                return {"transcript": transcript, "language": detected_lang}

        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Gnani STT request timed out."
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gnani STT connection error: {str(e)}"
            )


def get_stt_service() -> STTService:
    """Factory function returning the configured STT service."""
    if settings.APP_ENV == "test" or os.getenv("APP_ENV") == "test":
        return MockSTTService()
    provider = settings.STT_PROVIDER.lower()
    if provider == "gnani" or (provider != "mock" and settings.GNANI_API_KEY):
        return GnaniPrismaSTTService()
    return MockSTTService()
