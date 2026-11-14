"""
Subject CRUD routes (teachers create/edit, students view, teacher isolation enforced).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_teacher
from app.models.user import User, UserRole
from app.models.subject import Subject
from app.schemas.materials import (
    SubjectCreate,
    SubjectResponse,
    SubjectUpdate,
    ChapterResponse,
)

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.post("", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
def create_subject(
    body: SubjectCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Create a new subject owned by the authenticated teacher."""
    subject = Subject(
        name=body.name,
        description=body.description,
        teacher_id=teacher.id,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.get("", response_model=list[SubjectResponse])
def list_subjects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List subjects (teachers see their own subjects, students see all available subjects)."""
    if user.role == UserRole.teacher:
        return db.query(Subject).filter(Subject.teacher_id == user.id).all()
    return db.query(Subject).all()


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(
    subject_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific subject by ID (teachers can only access their own subjects)."""
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    if user.role == UserRole.teacher and subject.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    return subject


@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(
    subject_id: int,
    body: SubjectUpdate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Update a subject (teacher only)."""
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    if body.name is not None:
        subject.name = body.name
    if body.description is not None:
        subject.description = body.description

    db.commit()
    db.refresh(subject)
    return subject


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(
    subject_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Delete a subject (teacher only)."""
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    db.delete(subject)
    db.commit()
    return None


@router.get("/{subject_id}/chapters", response_model=list[ChapterResponse])
def list_subject_chapters(
    subject_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ready_only: bool = False,
):
    """List chapters for a specific subject.

    Students see ALL chapters of the subject (a chapter without material is shown
    with ``has_ready_documents=False`` so the UI can label it "No study material
    yet"); callers may still pass ``ready_only=true`` to filter those out.
    """
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    if user.role == UserRole.teacher and subject.teacher_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    if ready_only:
        return [chap for chap in subject.chapters if chap.has_ready_documents]
    return subject.chapters
