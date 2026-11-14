# SQLAlchemy ORM models.
# Import all models here so Alembic and Base.metadata can discover them.

from app.models.user import User, UserRole  # noqa: F401
from app.models.subject import Subject  # noqa: F401
from app.models.chapter import Chapter  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.document_chunk import DocumentChunk  # noqa: F401
