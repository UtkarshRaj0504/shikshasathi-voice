"""
Document upload, status, list, and delete routes (teacher-only).
"""

import os
import uuid
import mimetypes
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user, require_teacher
from app.models.user import User, UserRole
from app.models.subject import Subject
from app.models.chapter import Chapter
from app.models.document import Document
from app.schemas.materials import DocumentResponse
from app.services.document_processor import process_document

router = APIRouter(tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


@router.post("/chapters/{chapter_id}/documents/upload", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    chapter_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Upload a document (PDF, DOCX, TXT) to a chapter, validate size/type, and trigger background processing."""
    # 1. Verify chapter and teacher ownership
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    subject = db.query(Subject).filter(Subject.id == chapter.subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # 2. Validate file extension
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {list(ALLOWED_EXTENSIONS)}"
        )

    # 3. Validate file size (max 20 MB)
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    contents = await file.read()
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB"
        )

    # 4. Save file to UPLOAD_DIR
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    unique_filename = f"{uuid.uuid4()}_{filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as f:
        f.write(contents)

    # 5. Create Document DB record (status: pending)
    doc = Document(
        filename=filename,
        file_path=file_path,
        status="pending",
        chapter_id=chapter.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 6. Trigger background processing task
    background_tasks.add_task(process_document, doc.id)

    return doc


@router.get("/chapters/{chapter_id}/documents", response_model=list[DocumentResponse])
def list_chapter_documents(
    chapter_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all documents uploaded to a chapter (available to teachers and students)."""
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")
    return chapter.documents


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document_status(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get document status and details (available to teachers and students)."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return doc


@router.get("/documents/{document_id}/file")
def get_document_file(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stream document file with correct content type.
    - Students can only access documents with status 'ready'.
    - Teachers can only access documents belonging to their own subjects.
    - Unauthenticated requests are rejected by get_current_user (401).
    """
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    chapter = db.get(Chapter, doc.chapter_id)
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    subject = db.get(Subject, chapter.subject_id)
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    if user.role == UserRole.teacher:
        if subject.teacher_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: teacher does not own this document")
    elif user.role == UserRole.student:
        if doc.status != "ready":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: document is not ready")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on storage")

    content_type, _ = mimetypes.guess_type(doc.filename)
    if not content_type:
        ext = os.path.splitext(doc.filename)[1].lower()
        if ext == ".pdf":
            content_type = "application/pdf"
        elif ext == ".docx":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ext in [".txt", ".md"]:
            content_type = "text/plain; charset=utf-8"
        else:
            content_type = "application/octet-stream"

    return FileResponse(
        path=doc.file_path,
        media_type=content_type,
        filename=doc.filename,
        content_disposition_type="inline",
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Delete a document, its chunks, and its file from disk."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    chapter = db.get(Chapter, doc.chapter_id)
    subject = db.query(Subject).filter(Subject.id == chapter.subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Remove file from disk if it exists
    if os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except Exception:
            pass

    db.delete(doc)
    db.commit()
    return None
