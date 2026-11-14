"""
TTS (Text-to-Speech) service interface with Mock and Gnani Timbre implementations.
"""

import abc
import base64
import math
import struct
import httpx
from app.core.config import settings


class TTSService(abc.ABC):
    """Abstract base class for Text-to-Speech services."""

    @abc.abstractmethod
    def synthesize_speech(
        self,
        text: str,
        voice_id: str | None = None,
        language: str = "en",
        is_cloned: bool = False,
    ) -> bytes:
        """Synthesize text into WAV/MP3 audio bytes."""
        pass


class MockTTSService(TTSService):
    """
    Mock TTS service that generates a valid 16kHz mono WAV tone in memory.
    Fast, reliable, and completely offline for tests and development.
    """

    def synthesize_speech(
        self,
        text: str,
        voice_id: str | None = None,
        language: str = "en",
        is_cloned: bool = False,
    ) -> bytes:
        # Generate pitch according to cloned vs default voice
        freq = 320.0 if is_cloned else 440.0
        # Scale duration with text length (min 0.3s, max 2.0s)
        duration_s = max(0.3, min(2.0, len(text) * 0.015))
        sample_rate = 16000

        num_samples = int(duration_s * sample_rate)
        raw_data = bytearray()
        for i in range(num_samples):
            # Gentle envelope to prevent clicks
            envelope = min(1.0, (i / 800.0), ((num_samples - i) / 800.0))
            envelope = max(0.0, envelope)
            val = int(32767 * 0.15 * envelope * math.sin(2 * math.pi * freq * (i / sample_rate)))
            raw_data.extend(struct.pack("<h", val))

        header = bytearray()
        header.extend(b"RIFF")
        header.extend(struct.pack("<I", 36 + len(raw_data)))
        header.extend(b"WAVEfmt ")
        header.extend(struct.pack("<I", 16))
        header.extend(struct.pack("<H", 1))  # PCM format
        header.extend(struct.pack("<H", 1))  # 1 channel (mono)
        header.extend(struct.pack("<I", sample_rate))
        header.extend(struct.pack("<I", sample_rate * 2))
        header.extend(struct.pack("<H", 2))  # Block align
        header.extend(struct.pack("<H", 16))  # Bits per sample
        header.extend(b"data")
        header.extend(struct.pack("<I", len(raw_data)))

        return bytes(header + raw_data)


class GnaniTimbreTTSService(TTSService):
    """
    Gnani Timbre & Voice Cloning TTS API integration.
    """

    def synthesize_speech(
        self,
        text: str,
        voice_id: str | None = None,
        language: str = "en",
        is_cloned: bool = False,
    ) -> bytes:
        endpoint = (
            getattr(settings, "GNANI_VOICE_CLONE_ENDPOINT", "")
            if is_cloned
            else getattr(settings, "GNANI_TIMBRE_ENDPOINT", "")
        )
        api_key = getattr(settings, "GNANI_API_KEY", "")

        if not endpoint or not api_key:
            # Fall back to mock when credentials not configured
            return MockTTSService().synthesize_speech(
                text=text, voice_id=voice_id, language=language, is_cloned=is_cloned
            )

        headers = {
            "token": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "lang": language,
            "voice_id": voice_id,
        }

        with httpx.Client(timeout=15.0) as client:
            res = client.post(endpoint, headers=headers, json=payload)
            res.raise_for_status()
            data = res.json()
            # Audio is typically returned as base64 in data["audioContent"] or raw
            if "audioContent" in data:
                return base64.b64decode(data["audioContent"])
            return res.content


def get_tts_service() -> TTSService:
    """Return configured TTS service instance."""
    timbre_endpoint = getattr(settings, "GNANI_TIMBRE_ENDPOINT", "")
    api_key = getattr(settings, "GNANI_API_KEY", "")
    if timbre_endpoint and api_key:
        return GnaniTimbreTTSService()
    return MockTTSService()
