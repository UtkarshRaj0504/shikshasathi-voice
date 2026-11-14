"""
STT (Speech-to-Text) router for student voice question transcription.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.security import require_student
from app.models.user import User
from app.services.stt_service import get_stt_service

router = APIRouter(prefix="/stt", tags=["stt"])

ALLOWED_CONTENT_TYPES = [
    "audio/webm",
    "audio/wav",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/m4a",
    "audio/x-m4a",
    "application/octet-stream",
]


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language_code: str = Form("auto"),
    user: User = Depends(require_student),
):
    """
    Transcribe student voice audio upload (webm, wav, mp3).
    Student role required. Max size 10MB.
    """
    contents = await audio.read()

    # Max upload size 10MB as requested in Phase 4 spec
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file exceeds the 10MB size limit.",
        )

    if len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded audio file is empty.",
        )

    filename = audio.filename or "audio.webm"
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    allowed_exts = ["webm", "wav", "mp3", "ogg", "m4a"]

    if ext and ext not in allowed_exts and audio.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid audio file type or extension '.{ext}'. Allowed types: webm, wav, mp3, ogg, m4a.",
        )

    stt_service = get_stt_service()
    result = await stt_service.transcribe(contents, language_code, filename)
    return result
