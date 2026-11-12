"""
ShikshaSaathi Voice — FastAPI Application Entry Point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health", tags=["system"])
async def health_check():
    """Basic health-check endpoint."""
    return {"status": "ok", "version": app.version}
