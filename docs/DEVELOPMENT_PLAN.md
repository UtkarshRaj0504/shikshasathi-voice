# ShikshaSaathi Voice — Development Roadmap

## Overview
Multilingual AI-powered educational voice tutor for Indian languages. Students ask questions through microphone, get grounded answers in their language, spoken back.

## Phase Completion Status

### ✅ Phase 1: Auth & Data Foundation
- User registration/login (teacher + student)
- JWT tokens with role-based access
- PostgreSQL + SQLAlchemy models
- *Complete: Tests passing*

### ✅ Phase 2: Document Upload & RAG
- Teacher document upload (PDF, DOCX)
- Automatic chunking with page attribution
- Embedding with multilingual e5-small
- Semantic search with current-page boosting
- *Complete: Tests passing*

### ✅ Phase 3: Student Study Page
- Subject/Chapter selection
- PDF reader with page tracking
- Mic input, STT transcription
- /ask endpoint with RAG + LLM
- Answer display with sources
- AudioPlayer component
- *Complete: Tests passing*

### ✅ Phase 4: Voice Preferences & Streaming
- GET /voices (active teacher profiles with consent)
- PUT /me/preferences (voice selection)
- /tts/speak endpoint with default & cloned voices
- Graceful fallback from cloned to default
- Document file streaming
- Mock & Gnani TTS providers
- *Complete: Tests passing*

### ⏳ Phase 5: Multilingual Q&A Fix
- Diagnostic testing (kn/hi/en retrieval & LLM)
- Fix cross-language retrieval issues
- Answer in requested language
- *In progress: Task 2*

### 🚀 Phase 6: Real Consent & Teacher Voice Cloning
- VoiceConsent table (teacher_id, text, timestamp, IP, confirmed, revoked_at)
- Teacher-only endpoints: record sample, upload reference, tick consent, create profile, list, delete/revoke
- Profile preview with test sentence
- Connect profiles to /voices, preferences, /tts/speak
- "AI-generated voice, authorized by the teacher." label
- Tests: consent required, role checks, teacher isolation, revoke flow
- *In progress: Task 1*

### 🚀 Phase 7: Server-Side Conversations
- Conversation model (student_id, chapter_id, title, created_at)
- Message model (conversation_id, role, content, sources, grounded, language, voice_used, created_at)
- /ask takes conversation_id, loads history, rewrites follow-ups, saves messages
- Endpoints: list, get, delete conversations (student isolation)
- Frontend: history panel, continue old chat, New Chat, "explain simpler" / "give example" buttons
- Tests: follow-up context, ownership isolation, deletion, context limits
- *Planned: Task 3*

### ⏹️ Phase 8: Quizzes [DROPPED BY DECISION]
- Removed from roadmap (not part of this sprint)

### 🚀 Phase 9: Evaluation Harness
- evaluation/: 20-question JSON set (kn/hi/en with expected chunks & key points)
- Retrieval hit rate, correct refusal, per-step latency (STT, retrieval, LLM, TTS, total)
- STT word error rate from reference clips
- Reports into evaluation/results.md and CSV
- *Planned: Task 4*

### 🚀 Phase 10: Teacher Analytics
- Events: questions by chapter/language/grounded, voice used, time on page
- Teacher-scoped endpoints and dashboard page
- "Questions the notes could not answer" report
- CSV export, scoping tests
- *Planned: Task 5*

### 🚀 Phase 11: Hardening
- Rate limits on auth, /stt, /ask, /tts, uploads
- Protected routes return 401 without token
- Structured logs (no secrets, raw audio)
- docs/SECURITY.md
- docker-compose.yml (db, backend, frontend, keep :5433 working)
- GitHub Actions (tests, build)
- *Planned: Task 6*

### 🚀 Phase 12: Demo Prep
- scripts/seed_demo.py (clearly fake data)
- docs/DEMO_SCRIPT.md (5-minute flow, known limits)
- README accuracy pass
- *Planned: Task 7*

## Current Sprint: Fix TTS & Voice Cloning

### Task 0: Fix TTS (Beep Issue)
- Find root cause (Mock vs real provider selection, error fallback)
- Verify Gnani TTS against official docs (endpoint, headers, body, voice names, model, format, sample rate)
- Real failures return error code/message (no secrets), not beep
- Mock clearly labelled in UI
- Tests: success, 401/402/403/429, timeout, bad audio

### Task 1: Teacher Voice Cloning (Real Consent)
- VoiceCloneService interface (Mock + Gnani)
- VoiceConsent table & migration
- Teacher endpoints: record/upload sample, consent read & tick, create profile, list, preview, delete/revoke
- Connect profiles to /voices, preferences, /tts/speak
- Tests: consent required, no activation without, role checks, teacher isolation, revoke, mocked errors

### Task 2: Multilingual Q&A Fix
- Diagnostic script/test (bilingual fixture: English, Kannada, Hindi)
- Check: e5 prefixes, threshold, prompt language tags, Unicode normalization, STT codes (kn/hi), grounded flag
- Fix root causes, support all language combinations
- Regression tests, document findings

### Task 3: Server-Side Conversations
- Conversation & Message models
- /ask takes conversation_id, loads history, rewrites follow-ups
- Endpoints: list, get, delete (ownership isolation)
- Frontend: history panel, continue chat, New Chat, helper buttons
- Tests: follow-up context, ownership, deletion, context limits

### Task 4: Evaluation Harness
- 20-question JSON (kn/hi/en with expected chunks & key points)
- Scripts: retrieval hit rate, latency per step, STT WER from clips
- Results to evaluation/results.md and CSV
- README instructions

### Tasks 5-7 (if budget remains)
- Task 5: Teacher analytics & dashboard
- Task 6: Security hardening (rate limits, logs, docker-compose, CI)
- Task 7: Demo prep (seed script, demo flow doc, README)

## Key Decisions Recorded
See docs/DECISIONS.md for architectural decisions (page attribution, student visibility, consent & security, TTS fallback).
