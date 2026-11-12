# ShikshaSaathi Voice — Development Plan

> Phased roadmap. Each phase is a self-contained milestone.

---

## Phase 1 ✅ — Project Initialization

- Scaffold backend (FastAPI) and frontend (React + Vite) projects.
- Create directory structure, config files, environment template.
- Write README and this development plan.

---

## Phase 2 — Database & Authentication

- Set up PostgreSQL with pgvector extension.
- Define SQLAlchemy models: `User`, `Subject`, `Chapter`, `Document`.
- Configure Alembic for migrations.
- Implement JWT-based authentication (register, login, role-based access).
- Write tests for auth endpoints.

---

## Phase 3 — Teacher: Material Upload & Management

- Build file upload endpoints (PDF, DOCX, TXT).
- Parse documents (PyMuPDF) and extract text.
- Chunk text, generate embeddings (placeholder until Gnani integration), store in pgvector.
- CRUD API for subjects and chapters.
- Teacher dashboard frontend (upload, organize, view materials).
- Write tests for upload & retrieval.

---

## Phase 4 — Student: Voice Question Flow (STT)

- Integrate Gnani Prisma (Speech-to-Text) API.
- Build frontend audio recorder component.
- WebSocket or REST endpoint for streaming/uploading audio.
- Transcribe student questions and display text.
- Write tests with mock STT responses.

---

## Phase 5 — RAG: Retrieval-Augmented Answer Generation

- Implement vector similarity search over pgvector.
- Integrate Gnani Evon (LLM) to generate answers grounded in retrieved chunks.
- Build the answer generation pipeline with source citations.
- Clearly flag when material does not contain the answer.
- Write tests for retrieval accuracy and answer grounding.

---

## Phase 6 — Text-to-Speech Response

- Integrate Gnani Timbre (TTS) API.
- Stream or serve generated audio to the frontend.
- Build audio playback component.
- Write tests with mock TTS responses.

---

## Phase 7 — Voice Cloning (Authorized Teachers)

- Build teacher voice profile management (record, consent, upload).
- Integrate Gnani Voice Cloning API (only with explicit authorization).
- Allow students to hear answers in teacher's cloned voice.
- Write tests and authorization validation.

---

## Phase 8 — Conversation & Follow-ups

- Maintain per-session conversation context.
- Allow follow-up questions that reference prior answers.
- Build conversation history UI.

---

## Phase 9 — AI-Generated Quizzes

- Generate quizzes from uploaded materials via Gnani Evon.
- Multiple-choice and short-answer formats.
- Quiz-taking UI with scoring and feedback.

---

## Phase 10 — Teacher Analytics Dashboard

- Track student activity (questions asked, topics, time spent).
- Visualize learning patterns for teachers.
- Export reports.

---

## Phase 11 — Production Hardening

- Rate limiting, input validation, error handling.
- Logging and monitoring.
- Docker Compose for local development.
- CI/CD pipeline.
- Security audit.

---

*Each phase will be developed incrementally with tests and documentation.*
