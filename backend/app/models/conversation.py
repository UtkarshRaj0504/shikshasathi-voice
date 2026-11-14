"""
Conversation and Message models for Phase 8 (Server-side conversations).
Enables follow-up questions with context, message history, and persistence.
"""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False, default="Study Session")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    student: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821
    chapter: Mapped["Chapter"] = relationship("Chapter", lazy="selectin")  # noqa: F821
    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        "Message", back_populates="conversation", cascade="all, delete-orphan", lazy="selectin"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)

    # Message role and content
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # For assistant responses
    grounded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="en", nullable=False)
    voice_used: Mapped[str] = mapped_column(String(50), default="default", nullable=False)  # "default" | "cloned"

    # Sources (JSON-serialized list of source objects)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON

    # Audio (base64-encoded binary audio)
    audio_base64: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")  # noqa: F821
