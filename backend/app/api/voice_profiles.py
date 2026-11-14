"""
Teacher Voice Cloning API (/voice-profiles).

Teachers record/upload a short reference sample, read and accept the consent
statement, and create a cloned voice profile. Students never access these
endpoints; they only see the active voice list from GET /voices.

Security / privacy notes:
- A profile only ever becomes ``active`` through the explicit consent flow
  (``consent_confirmed=true`` on creation). There is no other way to set it.
- The reference audio is processed in memory and is never written to disk or
  exposed to students.
"""

import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Deque

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.voice_consent import VoiceConsent
from app.models.voice_profile import VoiceProfile
from app.services.audio_utils import AudioValidationError, validate_reference_audio
from app.services.tts_service import detect_audio_content_type
from app.services.voice_clone_service import VoiceCloneError, get_voice_clone_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice-profiles", tags=["voice-profiles"])

# Only these statuses describe a usable cloned voice. A "failed" attempt (the
# provider rejected the sample) and a "revoked" profile must never consume one of
# the teacher's profile slots — otherwise a few failed retries silently block the
# feature with an opaque HTTP 400.
USABLE_PROFILE_STATUSES = ("active", "pending")

CONSENT_TEXT_VERSION = "2.0"
CONSENT_TEXT = """
Voice cloning consent — please read carefully before ticking the box.

I consent to ShikshaSaathi creating a synthetic ("cloned") copy of my voice from a
short recording I provide, and using it to read study answers aloud to students.
I understand and agree that:

1. My recording is used only to build a voice model. Answers students hear will be
   AI-generated in my voice and are NOT a live recording of me speaking.
2. Every answer played in my cloned voice is clearly labelled
   "AI-generated voice, authorized by the teacher." Students cannot download or
   reuse my recording; my reference audio is never shared with students.
3. My cloned voice may only be used inside ShikshaSaathi for tutoring the study
   material on this platform.
4. I can delete or revoke my cloned voice at any time. Revoking immediately removes
   it from student voice choices and stops all further synthesis; the platform then
   falls back to the default voice. I can request deletion of my voice data with no
   penalty.
5. Voice cloning is only performed after I explicitly confirm this consent, and no
   voice profile can become active without it.

By ticking the box below I give my explicit, informed consent to voice cloning as
described above.
"""

# Fixed sentence synthesized when a teacher previews their cloned voice.
PREVIEW_SENTENCE = (
    "Hello! This is a short sample of my cloned voice, created with my permission, "
    "to help my students learn. I can delete it at any time."
)

# --- Simple in-memory rate limiting (per teacher, per action) ---
_RATE_LIMITS: dict[tuple[int, str], Deque[float]] = defaultdict(deque)


def reset_rate_limits() -> None:
    """Clear the in-memory rate-limit state (used by tests)."""
    _RATE_LIMITS.clear()


def _enforce_rate_limit(teacher_id: int, action: str, limit: int) -> None:
    window = max(1, int(getattr(settings, "VOICE_CLONE_RATE_WINDOW_SECONDS", 600)))
    now = time.monotonic()
    bucket = _RATE_LIMITS[(teacher_id, action)]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "VOICE_CLONE_RATE_LIMIT",
                "message": "Too many voice-cloning requests. Please wait a few minutes and try again.",
            },
        )
    bucket.append(now)


class VoiceProfileResponse(BaseModel):
    id: int
    teacher_id: int
    teacher_name: str
    voice_name: str
    status: str
    languages: str | None = None
    consent_confirmed: bool
    created_at: datetime

    class Config:
        from_attributes = True


class VoiceProfileListResponse(BaseModel):
    profiles: list[VoiceProfileResponse]


class PreviewResponse(BaseModel):
    audio_base64: str
    content_type: str = "audio/wav"
    label: str = "AI-generated voice, authorized by the teacher."
    is_mock: bool = False


def require_teacher_role(user: User = Depends(get_current_user)) -> User:
    """Only teachers may manage voice profiles."""
    if user.role != UserRole.teacher:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voice cloning is only available to teachers.",
        )
    return user


def _to_response(profile: VoiceProfile) -> VoiceProfileResponse:
    return VoiceProfileResponse(
        id=profile.id,
        teacher_id=profile.teacher_id,
        teacher_name=profile.teacher.name if profile.teacher else "Teacher",
        voice_name=profile.voice_name,
        status=profile.status,
        languages=profile.languages,
        consent_confirmed=profile.consent_confirmed,
        created_at=profile.created_at,
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _record_consent(db: Session, teacher: User, profile_id: int, request: Request) -> None:
    consent = VoiceConsent(
        teacher_id=teacher.id,
        voice_profile_id=profile_id,
        consent_text_version=CONSENT_TEXT_VERSION,
        full_consent_text=CONSENT_TEXT,
        confirmed=True,
        confirmed_at=datetime.utcnow(),
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent", "") or "")[:500],
    )
    db.add(consent)


def _revoke_consent_records(db: Session, profile_id: int, reason: str, detach: bool = False) -> None:
    """
    Mark consent records as revoked.

    When ``detach`` is True the record is unlinked from the profile (the FK is
    nullable) so that deleting the profile row keeps the consent audit trail.
    """
    records = (
        db.query(VoiceConsent)
        .filter(VoiceConsent.voice_profile_id == profile_id, VoiceConsent.revoked_at.is_(None))
        .all()
    )
    for record in records:
        record.revoked_at = datetime.utcnow()
        record.revoke_reason = reason
        if detach:
            record.voice_profile_id = None


@router.get("/consent")
def get_consent_details(
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """Return the current consent text and whether this teacher has already accepted it."""
    existing = (
        db.query(VoiceConsent)
        .filter(
            VoiceConsent.teacher_id == teacher.id,
            VoiceConsent.consent_text_version == CONSENT_TEXT_VERSION,
            VoiceConsent.confirmed.is_(True),
            VoiceConsent.revoked_at.is_(None),
        )
        .first()
    )
    return {
        "consent_text_version": CONSENT_TEXT_VERSION,
        "consent_text": CONSENT_TEXT,
        "confirmed": existing is not None,
        "max_profiles": int(getattr(settings, "VOICE_CLONE_MAX_PROFILES", 3)),
    }


@router.post("", response_model=VoiceProfileResponse)
def create_voice_profile(
    request: Request,
    file: UploadFile = File(...),
    voice_name: str = Form(...),
    consent_confirmed: bool = Form(False),
    languages: str | None = Form(None),
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Create a cloned voice profile from a reference sample.

    Requires explicit consent (``consent_confirmed=true``); a profile only becomes
    ``active`` through this flow. The reference audio is never stored on disk.
    """
    _enforce_rate_limit(
        teacher.id, "create", int(getattr(settings, "VOICE_CLONE_CREATE_RATE_LIMIT", 5))
    )

    if not consent_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CONSENT_REQUIRED",
                "message": "You must read and accept the voice-cloning consent statement first.",
            },
        )

    clean_name = (voice_name or "").strip()
    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_NAME", "message": "Please provide a display name for this voice."},
        )

    max_profiles = int(getattr(settings, "VOICE_CLONE_MAX_PROFILES", 3))
    usable_count = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.teacher_id == teacher.id,
            VoiceProfile.status.in_(USABLE_PROFILE_STATUSES),
        )
        .count()
    )
    if usable_count >= max_profiles:
        logger.warning(
            "Voice profile cap reached for teacher %s (%s usable of %s)",
            teacher.id,
            usable_count,
            max_profiles,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PROFILE_LIMIT_REACHED",
                "message": f"You can keep at most {max_profiles} voice profiles. Delete one before adding another.",
            },
        )

    audio_bytes = file.file.read()
    try:
        validate_reference_audio(audio_bytes, file.filename, file.content_type)
    except AudioValidationError as e:
        logger.warning("Reference audio rejected for teacher %s: %s", teacher.id, e.message)
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": "INVALID_AUDIO", "message": e.message},
        )

    # Reference audio lives only in memory and is discarded right after cloning.
    service = get_voice_clone_service()
    try:
        embedding_ref = service.create_voice(audio_bytes, filename=file.filename or "sample.wav")
    except VoiceCloneError as e:
        db.add(
            VoiceProfile(
                teacher_id=teacher.id,
                voice_name=clean_name,
                languages=languages,
                status="failed",
                consent_confirmed=True,
                consent_text=CONSENT_TEXT,
            )
        )
        db.commit()
        logger.warning("Voice clone failed for teacher %s: %s", teacher.id, e.error_code)
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.error_code, "message": e.message},
        )

    profile = VoiceProfile(
        teacher_id=teacher.id,
        voice_name=clean_name,
        gnani_voice_id=embedding_ref,
        languages=languages,
        status="active",
        consent_confirmed=True,
        consent_text=CONSENT_TEXT,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    _record_consent(db, teacher, profile.id, request)
    db.commit()
    db.refresh(profile)

    logger.info("Teacher %s created voice profile %s", teacher.id, profile.id)
    return _to_response(profile)


@router.get("", response_model=VoiceProfileListResponse)
def list_voice_profiles(
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """List the authenticated teacher's own voice profiles (never another teacher's)."""
    profiles = (
        db.query(VoiceProfile)
        .filter(VoiceProfile.teacher_id == teacher.id)
        .order_by(VoiceProfile.created_at.desc())
        .all()
    )
    return VoiceProfileListResponse(profiles=[_to_response(p) for p in profiles])


@router.post("/{profile_id}/preview", response_model=PreviewResponse)
def preview_voice_profile(
    profile_id: int,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """Synthesize a fixed test sentence in the teacher's cloned voice."""
    _enforce_rate_limit(
        teacher.id, "preview", int(getattr(settings, "VOICE_CLONE_PREVIEW_RATE_LIMIT", 10))
    )

    profile = db.get(VoiceProfile, profile_id)
    if not profile or profile.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found.")

    if profile.status != "active" or not profile.gnani_voice_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PROFILE_NOT_ACTIVE",
                "message": "This voice profile is not active. Delete it and create a new one.",
            },
        )

    language = "en"
    if profile.languages:
        language = profile.languages.split(",")[0].strip() or "en"

    service = get_voice_clone_service()
    try:
        audio = service.synthesize_with_cloned_voice(profile.gnani_voice_id, PREVIEW_SENTENCE, language)
    except VoiceCloneError as e:
        logger.warning("Voice preview failed for profile %s: %s", profile_id, e.error_code)
        raise HTTPException(status_code=e.status_code, detail={"code": e.error_code, "message": e.message})

    import base64

    return PreviewResponse(
        audio_base64=base64.b64encode(audio).decode("ascii"),
        content_type=detect_audio_content_type(audio),
        is_mock=service.is_mock,
    )


@router.delete("/{profile_id}")
def delete_voice_profile(
    profile_id: int,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """Delete a profile: revoke consent, remove provider data where possible, drop the row."""
    profile = db.get(VoiceProfile, profile_id)
    if not profile or profile.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found.")

    if profile.gnani_voice_id:
        try:
            get_voice_clone_service().delete_voice(profile.gnani_voice_id)
        except Exception:
            logger.warning("Best-effort provider voice delete failed for profile %s", profile_id)

    _revoke_consent_records(db, profile_id, "Teacher deleted voice profile", detach=True)
    db.delete(profile)
    db.commit()

    logger.info("Teacher %s deleted voice profile %s", teacher.id, profile_id)
    return {"status": "deleted", "message": "Voice profile deleted and consent revoked."}


@router.post("/{profile_id}/revoke", response_model=VoiceProfileResponse)
def revoke_voice_profile(
    profile_id: int,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """Deactivate a profile without deleting it, so students immediately fall back to the default voice."""
    profile = db.get(VoiceProfile, profile_id)
    if not profile or profile.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found.")

    profile.status = "revoked"
    profile.consent_confirmed = False

    if profile.gnani_voice_id:
        try:
            get_voice_clone_service().delete_voice(profile.gnani_voice_id)
        except Exception:
            logger.warning("Best-effort provider voice delete failed for profile %s", profile_id)

    _revoke_consent_records(db, profile_id, "Teacher revoked consent")
    db.commit()
    db.refresh(profile)

    logger.info("Teacher %s revoked voice profile %s", teacher.id, profile_id)
    return _to_response(profile)
