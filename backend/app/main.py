"""
ShikshaSaathi Voice — FastAPI Application Entry Point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.subjects import router as subjects_router
from app.api.chapters import router as chapters_router
from app.api.documents import router as documents_router
from app.core.config import settings

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

# Routers
app.include_router(auth_router)
app.include_router(subjects_router)
app.include_router(chapters_router)
app.include_router(documents_router)


@app.get("/health", tags=["system"])
async def health_check():
    """Basic health-check endpoint."""
    return {"status": "ok", "version": app.version}
