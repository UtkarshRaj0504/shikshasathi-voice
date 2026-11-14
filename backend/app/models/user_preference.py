"""
UserPreference model — stores student/user settings:
chosen teacher voice profile, question language, and answer language.
"""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    voice_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True
    )
    question_language: Mapped[str] = mapped_column(String(30), default="indic-auto", nullable=False)
    answer_language: Mapped[str] = mapped_column(String(30), default="en", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="preferences", lazy="selectin")  # noqa: F821
    voice_profile: Mapped["VoiceProfile | None"] = relationship("VoiceProfile", lazy="selectin")  # noqa: F821
