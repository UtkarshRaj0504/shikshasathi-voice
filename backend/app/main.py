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
from app.api.voice_profiles import router as voice_profiles_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, get_engine
from app.core.security import hash_password
from app.models.user import User
from app.db.seed import TEST_ACCOUNTS

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

    # Add embedding_model to document_chunks (stale-embedding detection)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE document_chunks ADD COLUMN embedding_model VARCHAR(255)"))
            conn.commit()
    except Exception:
        pass

    # Add languages to voice_profiles (existing dev databases created before this column)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE voice_profiles ADD COLUMN languages VARCHAR(200)"))
            conn.commit()
    except Exception:
        pass

    # Print active providers without secrets
    try:
        from app.services.stt_service import get_stt_service
        from app.services.tts_service import get_tts_service
        from app.services.llm_service import get_llm_service
        from app.services.voice_clone_service import get_voice_clone_service
        from app.services.embedding_service import embedding_service

        stt_svc = get_stt_service()
        tts_svc = get_tts_service()
        llm_svc = get_llm_service()
        vc_svc = get_voice_clone_service()
        embedding_real = getattr(embedding_service, "is_real_model", False)
        print("=" * 65)
        print("ShikshaSaathi Voice Active Providers:")
        print(f"  STT:        {stt_svc.__class__.__name__} (config: {settings.STT_PROVIDER}, mock: {stt_svc.__class__.__name__.startswith('Mock')})")
        print(f"  TTS:        {tts_svc.__class__.__name__} (config: {settings.TTS_PROVIDER}, mock: {tts_svc.is_mock})")
        print(f"  LLM:        {llm_svc.__class__.__name__} (config: {settings.LLM_PROVIDER}, model: {settings.LLM_MODEL})")
        print(f"  Embedding:  {embedding_service.active_model_name} (real: {embedding_real}, dim: {embedding_service.dimension})")
        print(f"  VoiceClone: {vc_svc.__class__.__name__} (config: {settings.VOICE_CLONE_PROVIDER}, mock: {getattr(vc_svc, 'is_mock', None)})")
        print("=" * 65)
    except Exception as e:
        print(f"Active provider display error: {e}")

    # Warn (without secrets) when stored chunks were indexed with a different model.
    if "pytest" not in sys.modules and os.getenv("APP_ENV") != "test":
        try:
            from app.services.document_processor import find_stale_documents
            db = SessionLocal()
            try:
                info = find_stale_documents(db)
                if info["stale_chunk_documents"]:
                    print(
                        "[RAG] WARNING: documents indexed with a different embedding model: "
                        f"{info['stale_chunk_documents']}. Run "
                        "'python backend/scripts/reembed_chunks.py' to fix retrieval."
                    )
            finally:
                db.close()
        except Exception as e:
            print(f"Stale-embedding check error: {e}")

    if "pytest" in sys.modules or os.getenv("APP_ENV") == "test":
        return

    # Seed default test accounts from centralized config
    db = SessionLocal()
    try:
        for account in TEST_ACCOUNTS:
            existing = db.query(User).filter(User.email == account["email"]).first()
            if not existing:
                user = User(
                    email=account["email"],
                    name=account["name"],
                    hashed_password=hash_password(account["password"]),
                    role=account["role"],
                    is_active=True,
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                print(f"✓ Seeded test account: {account['email']} / {account['password']}")

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
app.include_router(voice_profiles_router)


@app.get("/health", tags=["system"])
async def health_check():
    """Basic health-check endpoint."""
    return {"status": "ok", "version": app.version}
