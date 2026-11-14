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
from app.services.tts_service import get_tts_service

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
            logger.warning(f"Cloned voice synthesis failed ({e}). Falling back to default voice.")
            fallback = True
            notice = "Teacher voice unavailable; used default voice."

    if audio_bytes is None:
        # Default voice generation
        try:
            audio_bytes = tts_service.synthesize_speech(
                text=body.text,
                language=body.language,
                is_cloned=False,
            )
            voice_used = "default"
            is_cloned = False
        except Exception as e:
            logger.error(f"Default TTS synthesis failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Text-to-speech generation failed.",
            )

    # Return raw audio stream if client explicitly requested audio media type
    accept = request.headers.get("accept", "")
    if "audio/" in accept:
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "X-Voice-Used": voice_used,
                "X-Voice-Fallback": str(fallback).lower(),
            },
        )

    # Otherwise return JSON with audio base64 and metadata
    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    return SpeakResponse(
        audio_base64=audio_b64,
        content_type="audio/wav",
        voice_used=voice_used,
        is_cloned=is_cloned,
        fallback=fallback,
        notice=notice,
        label=label,
    )
