"""
Reference-audio validation for teacher voice cloning.

Gnani voice cloning accepts a WAV or MP3 sample with roughly 5-30 seconds of clear
speech (https://docs.gnani.ai — Voice Cloning / embeddings). We validate type, size
and duration locally so the teacher gets a precise message instead of an opaque
provider error.

WAV duration is read exactly from the RIFF header. MP3/WebM/Ogg durations are
*estimates* (nominal bitrate) because a full decode is out of scope; they are used
only for a helpful length check and never for correctness.
"""

import os
import struct

MIN_DURATION_SECONDS = 5.0
MAX_DURATION_SECONDS = 30.0
MIN_BYTES = 1000  # smaller than this cannot be ~5 s of speech
MAX_BYTES = 20 * 1024 * 1024  # mirrors MAX_UPLOAD_SIZE_MB

_MIME_TO_FORMAT = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/vnd.wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/x-mp3": "mp3",
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/opus": "ogg",
}

_EXT_TO_FORMAT = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".webm": "webm",
    ".ogg": "ogg",
}

# Rough bitrates used only to estimate duration for non-WAV containers.
_NOMINAL_BITRATE = {"mp3": 128000, "webm": 128000, "ogg": 64000}


class AudioValidationError(Exception):
    """Raised when a reference-audio sample is unsupported, too small or wrong length."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def detect_format(filename: str | None, content_type: str | None) -> str | None:
    """Return 'wav' | 'mp3' | 'webm' | 'ogg' for a supported upload, else None."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _MIME_TO_FORMAT:
        return _MIME_TO_FORMAT[ct]
    ext = os.path.splitext(filename or "")[1].lower()
    return _EXT_TO_FORMAT.get(ext)


def _wav_duration_seconds(data: bytes) -> float | None:
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        if chunk_id == b"fmt " and pos + 24 <= len(data):
            byte_rate = struct.unpack("<I", data[pos + 16 : pos + 20])[0]
            if byte_rate:
                # Scan forward for the data chunk to compute an exact duration.
                scan = pos + 8 + chunk_size + (chunk_size % 2)
                while scan + 8 <= len(data):
                    if data[scan : scan + 4] == b"data":
                        data_size = struct.unpack("<I", data[scan + 4 : scan + 8])[0]
                        return data_size / byte_rate
                    skip = struct.unpack("<I", data[scan + 4 : scan + 8])[0]
                    scan += 8 + skip + (skip % 2)
                return None
        if chunk_id == b"data":
            return None
        pos += 8 + chunk_size + (chunk_size % 2)
    return None


def estimate_duration_seconds(data: bytes, fmt: str) -> float | None:
    """Best-effort duration in seconds, or None when it cannot be determined."""
    if fmt == "wav":
        return _wav_duration_seconds(data)
    bitrate = _NOMINAL_BITRATE.get(fmt)
    if not bitrate:
        return None
    return (len(data) * 8) / bitrate


def validate_reference_audio(data: bytes, filename: str | None, content_type: str | None) -> str:
    """
    Validate a reference-audio upload and return its detected format.

    Raises AudioValidationError (HTTP 400) with a teacher-facing message when the
    format is unsupported, the sample is empty/too small, or the duration is not in
    the documented ~5-30 second range.
    """
    fmt = detect_format(filename, content_type)
    if fmt is None:
        raise AudioValidationError(
            "Unsupported audio format. Please upload a WAV or MP3 recording (WebM is also accepted)."
        )
    if not data or len(data) < MIN_BYTES:
        raise AudioValidationError(
            "The recording is too short or empty. Please record 5-30 seconds of clear speech."
        )
    if len(data) > MAX_BYTES:
        raise AudioValidationError(
            "The recording is too large (maximum 20 MB). Please upload a shorter sample."
        )

    duration = estimate_duration_seconds(data, fmt)
    if duration is not None:
        if duration < MIN_DURATION_SECONDS:
            raise AudioValidationError(
                f"The recording is only about {duration:.1f} seconds. "
                "Please record at least 5 seconds of clear speech."
            )
        if duration > MAX_DURATION_SECONDS:
            raise AudioValidationError(
                f"The recording is about {duration:.0f} seconds. "
                "Please keep the sample under 30 seconds."
            )
    return fmt
