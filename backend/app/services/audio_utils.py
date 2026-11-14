"""
Reference-audio validation and normalization for teacher voice cloning.

Gnani voice cloning accepts a WAV or MP3 sample with roughly 5-30 seconds of clear
speech (https://docs.gnani.ai — Voice Cloning / embeddings). We validate the upload
locally so the teacher gets a precise message instead of an opaque provider error.

Browsers record WebM/Opus, which the provider cannot decode and rejects with an
opaque HTTP 500. Every accepted sample is therefore transcoded to 16 kHz mono
16-bit WAV with PyAV (bundled FFmpeg) before it reaches the provider, and the
duration is checked on the *decoded* audio — a container-size estimate is
unreliable for WebM/Opus.
"""

import io
import logging
import os
import struct
import wave

logger = logging.getLogger(__name__)

MIN_DURATION_SECONDS = 5.0
MAX_DURATION_SECONDS = 30.0
MIN_BYTES = 1000  # smaller than this cannot be ~5 s of speech
MAX_BYTES = 20 * 1024 * 1024  # mirrors MAX_UPLOAD_SIZE_MB

# 16 kHz mono is the shape the voice-cloning provider expects for reference audio.
TARGET_SAMPLE_RATE = 16000

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


def validate_reference_audio(data: bytes, filename: str | None, content_type: str | None) -> str:
    """
    Validate a reference-audio upload's type and size, and return its detected format.

    Duration is *not* checked here: it is checked in normalize_reference_audio(),
    which knows the exact decoded length (a byte-size estimate is wrong for WebM/Opus,
    where the same speech can be a third of the size).
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
    return fmt


def _decode_to_wav16k(data: bytes) -> bytes:
    """Decode any container PyAV understands into mono 16 kHz 16-bit PCM WAV."""
    import av  # imported lazily so the FFmpeg libraries load only when needed

    pcm = bytearray()
    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SAMPLE_RATE)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                pcm.extend(bytes(out.planes[0])[: out.samples * 2])
        for out in resampler.resample(None):
            pcm.extend(bytes(out.planes[0])[: out.samples * 2])

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TARGET_SAMPLE_RATE)
        wav_file.writeframes(bytes(pcm))
    return buf.getvalue()


def normalize_reference_audio(data: bytes) -> bytes:
    """
    Transcode a reference sample to a 16 kHz mono 16-bit WAV the provider can decode.

    Input may be a browser WebM/Opus recording, an Ogg/MP3 file or an existing WAV;
    the output is always WAV. Raises AudioValidationError when the bytes cannot be
    decoded or the decoded length is outside the documented ~5-30 second window, so
    the teacher sees a clear message instead of the provider's opaque HTTP 500.
    """
    try:
        import av  # noqa: F401
    except ImportError:  # pragma: no cover - PyAV is a declared dependency
        logger.warning("PyAV is unavailable; passing the reference audio through unmodified.")
        return data

    try:
        wav = _decode_to_wav16k(data)
    except Exception as exc:
        logger.warning("Reference audio could not be decoded: %s", exc)
        raise AudioValidationError(
            "We could not read this recording. Please record 5-30 seconds of clear speech "
            "in a quiet room and try again."
        ) from exc

    duration = _wav_duration_seconds(wav)
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
    return wav
