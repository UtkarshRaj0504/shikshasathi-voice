"""Create a clearly fake teacher/student course for deployment smoke testing."""

from pathlib import Path
import sys

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.chapter import Chapter  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.subject import Subject  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services.document_processor import process_document  # noqa: E402


TEACHER_EMAIL = "teacher.demo@example.test"
STUDENT_EMAIL = "student.demo@example.test"
DEMO_PASSWORD = "fake-demo-password-not-for-production"
SUBJECT_NAME = "Demo Plant Science"
CHAPTER_TITLE = "Photosynthesis"
DOCUMENT_NAME = "demo-photosynthesis.txt"
DOCUMENT_TEXT = (
    "Plants use photosynthesis to make sugars. Chlorophyll in green leaves captures "
    "light energy. The plant uses that energy to combine water and carbon dioxide "
    "into sugar and oxygen. Roots absorb water, and leaves take in carbon dioxide."
)


def get_or_create_user(db, email: str, name: str, role: UserRole) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            email=email,
            name=name,
            hashed_password=hash_password(DEMO_PASSWORD),
            role=role,
        )
        db.add(user)
        db.flush()
    return user


def main() -> None:
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(alembic_config, "head")

    document_id = None
    should_process = False
    with SessionLocal() as db:
        teacher = get_or_create_user(db, TEACHER_EMAIL, "Demo Teacher", UserRole.teacher)
        get_or_create_user(db, STUDENT_EMAIL, "Demo Student", UserRole.student)

        subject = (
            db.query(Subject)
            .filter(Subject.teacher_id == teacher.id, Subject.name == SUBJECT_NAME)
            .first()
        )
        if subject is None:
            subject = Subject(
                name=SUBJECT_NAME,
                description="Fake sample course for deployment checks.",
                teacher_id=teacher.id,
            )
            db.add(subject)
            db.flush()

        chapter = (
            db.query(Chapter)
            .filter(Chapter.subject_id == subject.id, Chapter.title == CHAPTER_TITLE)
            .first()
        )
        if chapter is None:
            chapter = Chapter(title=CHAPTER_TITLE, order=1, subject_id=subject.id)
            db.add(chapter)
            db.flush()

        document = (
            db.query(Document)
            .filter(Document.chapter_id == chapter.id, Document.filename == DOCUMENT_NAME)
            .first()
        )
        if document is None:
            content = DOCUMENT_TEXT.encode("utf-8")
            if settings.STORAGE_PROVIDER == "database":
                document = Document(
                    filename=DOCUMENT_NAME,
                    file_data=content,
                    status="pending",
                    chapter_id=chapter.id,
                )
            else:
                upload_dir = Path(settings.UPLOAD_DIR)
                upload_dir.mkdir(parents=True, exist_ok=True)
                local_path = upload_dir / DOCUMENT_NAME
                local_path.write_bytes(content)
                document = Document(
                    filename=DOCUMENT_NAME,
                    file_path=str(local_path),
                    status="pending",
                    chapter_id=chapter.id,
                )
            db.add(document)
            db.flush()
            should_process = True
        elif document.status != "ready":
            should_process = True

        document_id = document.id
        db.commit()

    if should_process and document_id is not None:
        process_document(document_id)
        with SessionLocal() as db:
            document = db.get(Document, document_id)
            if document is None or document.status != "ready":
                raise SystemExit("Demo sample document could not be indexed.")

    print("Fake demo teacher, student, subject, chapter, and sample document are ready.")


if __name__ == "__main__":
    main()
