"""
Teacher Voice Cloning API endpoints.
Teachers can record/upload reference audio, read & confirm consent, create profiles, and manage them.
Students never access these endpoints; they only see the voice list in GET /voices.
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.voice_profile import VoiceProfile
from app.models.voice_consent import VoiceConsent
from app.services.voice_clone_service import VoiceCloneError, get_voice_clone_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice-profiles", tags=["voice-profiles"])

# Current consent text version
CONSENT_TEXT_VERSION = "1.0"
CONSENT_TEXT = """
I hereby consent to ShikshaSaathi using my recorded voice sample to create a cloned voice profile for educational purposes. I understand that:

1. My voice will be analyzed to generate a speaker embedding used for text-to-speech synthesis in study materials.
2. Students selecting my cloned voice will see a transparency notice: "AI-generated voice, authorized by the teacher."
3. My cloned voice can only be used within ShikshaSaathi by students studying materials I've authored or approved.
4. I can revoke this consent at any time, which will immediately deactivate my voice profiles and remove the cloned voice from future student responses.
5. ShikshaSaathi retains the right to delete the speaker embedding if my account is deleted or if the service is discontinued.

By confirming below, I grant explicit, informed consent for voice cloning as described above.
"""


class ConsentCheckRequest(BaseModel):
    """Check if teacher has confirmed the current consent version."""
    pass


class ConsentConfirmRequest(BaseModel):
    """Confirm consent and prepare for voice profile creation."""
    confirmed: bool = Field(default=True)
    ip_address: str | None = None
    user_agent: str | None = None


class VoiceProfileCreateRequest(BaseModel):
    """Create a new voice profile after consent is confirmed."""
    voice_name: str = Field(min_length=1, max_length=200)


class VoiceProfileResponse(BaseModel):
    """Voice profile for teacher management (full details)."""
    id: int
    voice_name: str
    status: str
    consent_confirmed: bool
    gnani_voice_id: str | None
    sample_audio_path: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class TeacherVoiceListResponse(BaseModel):
    """List of teacher's voice profiles."""
    profiles: list[VoiceProfileResponse]


def require_teacher_role(user: User = Depends(get_current_user)):
    """Dependency to ensure only teachers access voice cloning endpoints."""
    if user.role != UserRole.teacher:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voice cloning is only available to teachers."
        )
    return user


@router.get("/consent", response_model=dict)
def get_consent_details(
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Get current consent text and check if teacher has confirmed the current version.
    """
    # Check if teacher has confirmed consent for current version
    latest_consent = (
        db.query(VoiceConsent)
        .filter(
            VoiceConsent.teacher_id == teacher.id,
            VoiceConsent.consent_text_version == CONSENT_TEXT_VERSION,
            VoiceConsent.confirmed == True,
            VoiceConsent.revoked_at == None,
        )
        .order_by(VoiceConsent.created_at.desc())
        .first()
    )

    return {
        "consent_text_version": CONSENT_TEXT_VERSION,
        "consent_text": CONSENT_TEXT,
        "confirmed": latest_consent is not None,
        "confirmed_at": latest_consent.confirmed_at if latest_consent else None,
    }


@router.post("/consent/confirm")
def confirm_consent(
    body: ConsentConfirmRequest,
    request: Request,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Teacher confirms the consent statement. Required before creating a voice profile.
    Stores IP and user-agent for audit trail.
    """
    if not body.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent must be confirmed to proceed."
        )

    # Check if already confirmed for this version
    existing = (
        db.query(VoiceConsent)
        .filter(
            VoiceConsent.teacher_id == teacher.id,
            VoiceConsent.consent_text_version == CONSENT_TEXT_VERSION,
            VoiceConsent.confirmed == True,
            VoiceConsent.revoked_at == None,
        )
        .first()
    )

    if existing:
        return {
            "status": "already_confirmed",
            "message": "You have already confirmed consent for this version.",
            "confirmed_at": existing.confirmed_at,
        }

    # Create new consent record
    consent = VoiceConsent(
        teacher_id=teacher.id,
        consent_text_version=CONSENT_TEXT_VERSION,
        full_consent_text=CONSENT_TEXT,
        confirmed=True,
        confirmed_at=datetime.utcnow(),
        ip_address=body.ip_address or request.client.host if request.client else None,
        user_agent=body.user_agent or request.headers.get("user-agent", "")[:500],
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)

    logger.info(f"Teacher {teacher.id} confirmed voice cloning consent version {CONSENT_TEXT_VERSION}")

    return {
        "status": "confirmed",
        "message": "Consent confirmed. You can now create voice profiles.",
        "confirmed_at": consent.confirmed_at,
    }


@router.post("/upload-reference-audio")
async def upload_reference_audio(
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Upload a reference audio sample (5-30 seconds) and generate a speaker embedding.
    The embedding is stored and will be used when creating a voice profile.
    """
    # Verify consent is confirmed
    has_consent = (
        db.query(VoiceConsent)
        .filter(
            VoiceConsent.teacher_id == teacher.id,
            VoiceConsent.consent_text_version == CONSENT_TEXT_VERSION,
            VoiceConsent.confirmed == True,
            VoiceConsent.revoked_at == None,
        )
        .first()
    )

    if not has_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must confirm the consent statement before uploading audio.",
        )

    # Validate file type
    allowed_types = {"audio/wav", "audio/mpeg", "audio/mp3"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only WAV and MP3 audio files are supported.",
        )

    # Read and validate audio size
    audio_bytes = await file.read()
    if len(audio_bytes) < 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is too small. Please provide at least 5 seconds of clear speech.",
        )

    # Generate embedding via voice clone service
    vc_service = get_voice_clone_service()
    try:
        embedding = vc_service.create_embedding(audio_bytes, filename=file.filename or "sample.wav")
    except VoiceCloneError as e:
        logger.warning(f"Voice cloning failed for teacher {teacher.id}: {e.message}")
        raise HTTPException(status_code=e.status_code, detail=e.message)

    logger.info(f"Teacher {teacher.id} uploaded reference audio, generated embedding")

    return {
        "status": "success",
        "embedding_id": embedding,
        "message": "Reference audio processed successfully. Use this embedding to create a voice profile.",
    }


@router.post("/create", response_model=VoiceProfileResponse)
def create_voice_profile(
    body: VoiceProfileCreateRequest,
    request: Request,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Create a new voice profile after consent is confirmed and reference audio is uploaded.
    Profile is initially created but not active until consent_confirmed is verified.
    """
    # Verify consent is confirmed
    has_consent = (
        db.query(VoiceConsent)
        .filter(
            VoiceConsent.teacher_id == teacher.id,
            VoiceConsent.consent_text_version == CONSENT_TEXT_VERSION,
            VoiceConsent.confirmed == True,
            VoiceConsent.revoked_at == None,
        )
        .first()
    )

    if not has_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must confirm the consent statement before creating a voice profile.",
        )

    # Create voice profile (will be active once consent_confirmed is True)
    profile = VoiceProfile(
        teacher_id=teacher.id,
        voice_name=body.voice_name,
        status="active",
        consent_confirmed=True,
        consent_text=CONSENT_TEXT,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    # Link consent record to this profile
    has_consent.voice_profile_id = profile.id
    db.commit()

    logger.info(f"Teacher {teacher.id} created voice profile {profile.id}: {body.voice_name}")

    return VoiceProfileResponse.from_orm(profile)


@router.get("/list", response_model=TeacherVoiceListResponse)
def list_teacher_profiles(
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    List all voice profiles for the authenticated teacher.
    Only teachers can see their own profiles (full details).
    """
    profiles = db.query(VoiceProfile).filter(
        VoiceProfile.teacher_id == teacher.id
    ).order_by(VoiceProfile.created_at.desc()).all()

    return TeacherVoiceListResponse(
        profiles=[VoiceProfileResponse.from_orm(p) for p in profiles]
    )


@router.get("/{profile_id}", response_model=VoiceProfileResponse)
def get_profile_details(
    profile_id: int,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Get details of a specific voice profile (teacher can only see their own).
    """
    profile = db.get(VoiceProfile, profile_id)
    if not profile or profile.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found.")

    return VoiceProfileResponse.from_orm(profile)


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: int,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Delete a voice profile and revoke consent.
    Immediately deactivates the profile and removes it from student voice selection.
    """
    profile = db.get(VoiceProfile, profile_id)
    if not profile or profile.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found.")

    # Revoke associated consent records
    consents = db.query(VoiceConsent).filter(
        VoiceConsent.voice_profile_id == profile_id
    ).all()

    for consent in consents:
        if consent.revoked_at is None:
            consent.revoked_at = datetime.utcnow()
            consent.revoke_reason = "Teacher deleted voice profile"

    # Delete the profile
    db.delete(profile)
    db.commit()

    logger.info(f"Teacher {teacher.id} deleted voice profile {profile_id}")

    return {
        "status": "deleted",
        "message": "Voice profile has been deleted and consent has been revoked.",
    }


@router.post("/{profile_id}/revoke-consent")
def revoke_consent(
    profile_id: int,
    teacher: User = Depends(require_teacher_role),
    db: Session = Depends(get_db),
):
    """
    Revoke consent for a specific voice profile without deleting it.
    The profile remains in the database but is marked inactive and unavailable to students.
    """
    profile = db.get(VoiceProfile, profile_id)
    if not profile or profile.teacher_id != teacher.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice profile not found.")

    # Mark profile as inactive
    profile.status = "inactive"
    profile.consent_confirmed = False

    # Revoke associated consent records
    consents = db.query(VoiceConsent).filter(
        VoiceConsent.voice_profile_id == profile_id,
        VoiceConsent.revoked_at == None,
    ).all()

    for consent in consents:
        consent.revoked_at = datetime.utcnow()
        consent.revoke_reason = "Teacher revoked consent"

    db.commit()

    logger.info(f"Teacher {teacher.id} revoked consent for voice profile {profile_id}")

    return {
        "status": "revoked",
        "message": "Consent has been revoked. The voice profile is now inactive.",
    }
