"""
VoiceConsent model — tracks teacher consent for voice cloning with full audit trail.
Required before a VoiceProfile can be activated (consent_confirmed=True).
"""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VoiceConsent(Base):
    __tablename__ = "voice_consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    voice_profile_id: Mapped[int | None] = mapped_column(ForeignKey("voice_profiles.id", ondelete="CASCADE"), nullable=True)

    # Consent tracking
    consent_text_version: Mapped[str] = mapped_column(String(50), default="1.0", nullable=False)
    full_consent_text: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Audit trail
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Revocation
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    teacher: Mapped["User"] = relationship("User", lazy="selectin")  # noqa: F821
    voice_profile: Mapped["VoiceProfile"] = relationship("VoiceProfile", lazy="selectin")  # noqa: F821
