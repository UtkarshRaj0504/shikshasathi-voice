"""
ShikshaSaathi Voice — FastAPI Application Entry Point
"""

import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.chapters import router as chapters_router
from app.api.documents import router as documents_router
from app.api.stt import router as stt_router
from app.api.subjects import router as subjects_router
from app.api.ask import router as ask_router
from app.api.preferences import router as preferences_router
from app.api.tts import router as tts_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, get_engine
from app.core.security import hash_password
from app.models.user import User
from app.models.voice_profile import VoiceProfile

app = FastAPI(
    title="ShikshaSaathi Voice API",
    description="Multilingual AI-powered educational voice tutor",
    version="0.1.0",
)

# CORS — allow the Vite dev server during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Create database tables and seed default users on startup (non-test mode)."""
    import app.models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    # Add page_number to document_chunks if table already existed without it
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE document_chunks ADD COLUMN page_number INTEGER"))
            conn.commit()
    except Exception:
        pass

    if "pytest" in sys.modules or os.getenv("APP_ENV") == "test":
        return

    # Seed default test accounts
    db = SessionLocal()
    try:
        teacher = db.query(User).filter(User.email == "teacher@example.com").first()
        if not teacher:
            teacher = User(
                email="teacher@example.com",
                name="Dr. Sharma",
                hashed_password=hash_password("securepassword123"),
                role="teacher",
            )
            db.add(teacher)
            db.commit()
            db.refresh(teacher)

        if not db.query(User).filter(User.email == "student@example.com").first():
            student = User(
                email="student@example.com",
                name="Rahul",
                hashed_password=hash_password("securepassword123"),
                role="student",
            )
            db.add(student)
            db.commit()

        # Seed an active teacher voice profile with confirmed consent
        if teacher and not db.query(VoiceProfile).filter(VoiceProfile.teacher_id == teacher.id).first():
            profile = VoiceProfile(
                teacher_id=teacher.id,
                voice_name="Dr. Sharma's Voice",
                gnani_voice_id="dr_sharma_v1",
                status="active",
                consent_confirmed=True,
                consent_text="I, Dr. Sharma, authorize ShikshaSaathi to use my cloned voice for tutoring.",
            )
            db.add(profile)
            db.commit()

    except Exception as e:
        print(f"Startup seeding error: {e}")
    finally:
        db.close()


# Routers
app.include_router(auth_router)
app.include_router(subjects_router)
app.include_router(chapters_router)
app.include_router(documents_router)
app.include_router(stt_router)
app.include_router(ask_router)
app.include_router(preferences_router)
app.include_router(tts_router)


@app.get("/health", tags=["system"])
async def health_check():
    """Basic health-check endpoint."""
    return {"status": "ok", "version": app.version}
