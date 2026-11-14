"""
Subject CRUD routes (teacher-only, scoped to current teacher).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_teacher
from app.models.user import User
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
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """List all subjects owned by the authenticated teacher."""
    return db.query(Subject).filter(Subject.teacher_id == teacher.id).all()


@router.get("/{subject_id}", response_model=SubjectResponse)
def get_subject(
    subject_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Get a specific subject by ID (must belong to teacher)."""
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    return subject


@router.put("/{subject_id}", response_model=SubjectResponse)
def update_subject(
    subject_id: int,
    body: SubjectUpdate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Update a subject."""
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
    """Delete a subject and all its chapters/documents."""
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    db.delete(subject)
    db.commit()
    return None


@router.get("/{subject_id}/chapters", response_model=list[ChapterResponse])
def list_subject_chapters(
    subject_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """List chapters for a specific subject owned by teacher."""
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    return subject.chapters
