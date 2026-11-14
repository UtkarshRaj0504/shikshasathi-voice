"""
Chapter CRUD routes (teacher-only, scoped to subject ownership).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_teacher
from app.models.user import User
from app.models.subject import Subject
from app.models.chapter import Chapter
from app.schemas.materials import (
    ChapterCreate,
    ChapterResponse,
    ChapterUpdate,
)

router = APIRouter(prefix="/subjects", tags=["chapters"])


@router.post("/{subject_id}/chapters", response_model=ChapterResponse, status_code=status.HTTP_201_CREATED)
def create_chapter(
    subject_id: int,
    body: ChapterCreate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Create a chapter within a subject owned by the teacher."""
    subject = db.query(Subject).filter(Subject.id == subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")

    chapter = Chapter(
        title=body.title,
        order=body.order,
        subject_id=subject.id,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


@router.put("/chapters/{chapter_id}", response_model=ChapterResponse)
def update_chapter(
    chapter_id: int,
    body: ChapterUpdate,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Update a chapter (verifying subject ownership)."""
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    # Verify subject ownership
    subject = db.query(Subject).filter(Subject.id == chapter.subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if body.title is not None:
        chapter.title = body.title
    if body.order is not None:
        chapter.order = body.order

    db.commit()
    db.refresh(chapter)
    return chapter


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chapter(
    chapter_id: int,
    teacher: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Delete a chapter and its documents."""
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    subject = db.query(Subject).filter(Subject.id == chapter.subject_id, Subject.teacher_id == teacher.id).first()
    if not subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    db.delete(chapter)
    db.commit()
    return None
