"""
TTS (Text-to-Speech) API endpoint (/tts/speak).
Supports default synthetic voice and authorized teacher cloned voice with graceful fallback.
"""

import base64
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.voice_profile import VoiceProfile
from app.services.tts_service import TTSError, detect_audio_content_type, get_tts_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["tts"])


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voice_profile_id: int | None = None
    language: str = Field(default="en")


class SpeakResponse(BaseModel):
    audio_base64: str
    content_type: str = "audio/wav"
    voice_used: str  # "cloned" | "default"
    is_cloned: bool
    is_mock: bool = False
    fallback: bool
    notice: str | None = None
    label: str | None = None


@router.post("/speak", response_model=SpeakResponse)
def speak_text(
    body: SpeakRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Synthesize answer text into speech.
    - If a valid, active voice profile with confirmed consent is specified, uses cloned teacher voice.
    - If the cloned voice fails or profile is invalid, falls back to the default voice with a notice.
    - Never silently falls back to a beep tone when real provider fails: returns explicit errors.
    - Cloned voice playback includes the explicit authorized disclosure label.
    """
    tts_service = get_tts_service()

    target_profile: VoiceProfile | None = None
    use_cloned = False
    fallback = False
    notice: str | None = None

    if body.voice_profile_id is not None:
        target_profile = db.get(VoiceProfile, body.voice_profile_id)
        if (
            target_profile
            and target_profile.status.lower() == "active"
            and target_profile.consent_confirmed
        ):
            use_cloned = True
        else:
            # Voice requested is invalid, unconfirmed, or inactive -> graceful fallback
            fallback = True
            notice = "Selected teacher voice profile is not active or unauthorized; used default voice."

    audio_bytes: bytes | None = None
    voice_used = "default"
    is_cloned = False
    label: str | None = None

    if use_cloned and target_profile:
        try:
            audio_bytes = tts_service.synthesize_speech(
                text=body.text,
                voice_id=target_profile.gnani_voice_id or str(target_profile.id),
                language=body.language,
                is_cloned=True,
            )
            voice_used = "cloned"
            is_cloned = True
            label = "AI-generated voice, authorized by the teacher."
        except Exception as e:
            err_msg = e.message if isinstance(e, TTSError) else "cloned voice synthesis failed"
            logger.warning("Cloned voice synthesis failed. Falling back to default voice.")
            fallback = True
            notice = f"Teacher voice unavailable ({err_msg}); used default voice."

    if audio_bytes is None:
        # Default voice: never replace a real-provider failure with a mock beep.
        try:
            audio_bytes = tts_service.synthesize_speech(
                text=body.text,
                language=body.language,
                is_cloned=False,
            )
            voice_used = "default"
            is_cloned = False
        except TTSError as err:
            logger.error("Default TTS synthesis error: %s", err.error_code)
            raise HTTPException(
                status_code=err.status_code,
                detail={"code": err.error_code, "message": err.message},
            )
        except Exception:
            logger.error("Default TTS unexpected synthesis failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "TTS_FAILED", "message": "Text-to-speech generation failed."},
            )

    content_type = detect_audio_content_type(audio_bytes)

    accept = request.headers.get("accept", "")
    if "audio/" in accept:
        return Response(
            content=audio_bytes,
            media_type=content_type,
            headers={
                "X-Voice-Used": voice_used,
                "X-Voice-Fallback": str(fallback).lower(),
                "X-Voice-Mock": str(tts_service.is_mock).lower(),
            },
        )

    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    return SpeakResponse(
        audio_base64=audio_b64,
        content_type=content_type,
        voice_used=voice_used,
        is_cloned=is_cloned,
        is_mock=tts_service.is_mock,
        fallback=fallback,
        notice=notice,
        label=label,
    )
