"""
User preferences and voice profile endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.voice_profile import VoiceProfile
from app.models.user_preference import UserPreference

router = APIRouter(tags=["preferences"])


class PreferencePayload(BaseModel):
    voice_profile_id: int | None = None
    question_language: str = Field(default="indic-auto")
    answer_language: str = Field(default="en")


class PreferenceResponse(BaseModel):
    voice_profile_id: int | None = None
    question_language: str = "indic-auto"
    answer_language: str = "en"


class VoiceProfileItem(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str
    voice_name: str
    status: str
    consent_confirmed: bool
    is_cloned: bool = True


@router.get("/me/preferences", response_model=PreferenceResponse)
@router.get("/auth/me/preferences", response_model=PreferenceResponse)
def get_preferences(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the current user's preferences (voice profile and languages)."""
    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        return PreferenceResponse(
            voice_profile_id=None,
            question_language="indic-auto",  # Default for STT auto-detection
            answer_language="en",  # Default for TTS/LLM
        )
    return PreferenceResponse(
        voice_profile_id=pref.voice_profile_id,
        question_language=pref.question_language or "indic-auto",
        answer_language=pref.answer_language or "en",
    )


@router.put("/me/preferences", response_model=PreferenceResponse)
@router.put("/auth/me/preferences", response_model=PreferenceResponse)
def update_preferences(
    body: PreferencePayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Save or update the current user's preferences.
    If voice_profile_id is set, it must belong to an active profile with confirmed consent.
    """
    if body.voice_profile_id is not None:
        vp = db.get(VoiceProfile, body.voice_profile_id)
        if not vp or vp.status.lower() != "active" or not vp.consent_confirmed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected voice profile is not active or lacks confirmed teacher consent",
            )

    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        pref = UserPreference(
            user_id=user.id,
            voice_profile_id=body.voice_profile_id,
            question_language=body.question_language,
            answer_language=body.answer_language,
        )
        db.add(pref)
    else:
        pref.voice_profile_id = body.voice_profile_id
        pref.question_language = body.question_language
        pref.answer_language = body.answer_language

    db.commit()
    db.refresh(pref)

    return PreferenceResponse(
        voice_profile_id=pref.voice_profile_id,
        question_language=pref.question_language or "indic-auto",
        answer_language=pref.answer_language or "en",
    )


@router.get("/voices", response_model=list[VoiceProfileItem])
def list_active_voices(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List teacher voice profiles that are ACTIVE and have confirmed consent.
    Available to students and teachers. Reference audio is never exposed here.
    """
    profiles = (
        db.query(VoiceProfile)
        .filter(VoiceProfile.status == "active", VoiceProfile.consent_confirmed.is_(True))
        .all()
    )

    result = []
    for vp in profiles:
        result.append(
            VoiceProfileItem(
                id=vp.id,
                teacher_id=vp.teacher_id,
                teacher_name=vp.teacher.name if vp.teacher else "Teacher",
                voice_name=vp.voice_name,
                status=vp.status,
                consent_confirmed=vp.consent_confirmed,
                is_cloned=True,
            )
        )
    return result
