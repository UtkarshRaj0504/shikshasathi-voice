"""
Chapter model — a chapter within a subject.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    subject: Mapped["Subject"] = relationship(back_populates="chapters")  # noqa: F821
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="chapter", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def ready_document_count(self) -> int:
        """Documents in this chapter that finished processing successfully."""
        return sum(1 for doc in self.documents if doc.status == "ready")

    @property
    def has_ready_documents(self) -> bool:
        """Whether at least one document in this chapter is ready to study."""
        return any(doc.status == "ready" for doc in self.documents)
