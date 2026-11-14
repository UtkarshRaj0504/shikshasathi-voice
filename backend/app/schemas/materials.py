"""
Pydantic schemas for subjects, chapters, and documents.
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ---- Subject Schemas ----

class SubjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class SubjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None


class SubjectResponse(BaseModel):
    id: int
    name: str
    description: str | None
    teacher_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Chapter Schemas ----

class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    order: int = 0


class ChapterUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    order: int | None = None


class ChapterResponse(BaseModel):
    id: int
    title: str
    order: int
    subject_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Document Schemas ----

class DocumentResponse(BaseModel):
    id: int
    filename: str
    status: str
    error_message: str | None
    chapter_id: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}
