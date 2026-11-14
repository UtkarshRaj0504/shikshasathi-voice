"""
VoiceProfile model — stores teacher voice profiles for cloned TTS.
Only profiles with status="active" and consent_confirmed=True are usable.
"""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    voice_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Provider reference for the cloned voice (the serialized speaker embedding for Gnani).
    gnani_voice_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Comma-separated BCP-47 language codes the teacher recorded the sample in.
    languages: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # pending | active | failed | revoked — a profile is only ever "active" through the consent flow.
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_audio_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    teacher: Mapped["User"] = relationship("User", back_populates="voice_profiles", lazy="selectin")  # noqa: F821
