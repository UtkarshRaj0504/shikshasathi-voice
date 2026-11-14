# Architectural & Design Decisions

## 1. Document Chunk Page Attribution & Current-Page Boosting

* **Context**: When reading long educational PDFs, student queries are frequently related to the active page currently in view in the reader.
* **Decision**: We added an optional `page_number` column (integer) to `DocumentChunk`. During document processing (`process_document`), PyMuPDF parses the document page-by-page via `extract_document_pages`, attributing each chunk to its corresponding 1-indexed PDF page.
* **Query Boosting**: `/ask` accepts an optional `current_page: int | None` parameter. When present, chunks originating from `current_page` receive a relevance score boost (+0.2), elevating chunks from the active page in the reader without suppressing strong global matches.

## 2. Document & Chapter Student Visibility ("Published" State)

* **Context**: Students must only have access to fully processed, ready materials and chapters that contain actual study content.
* **Decision**: Rather than introducing a redundant "published" toggle, all documents with `status == "ready"` are treated as visible.
* **Enforcement**:
  - `GET /subjects/{id}/chapters` filters chapters for student users so only chapters having at least one `status == "ready"` document are returned.
  - `GET /documents/{id}/file` permits students to stream only documents with `status == "ready"`. Any attempt to access "pending", "processing", or "failed" documents returns HTTP 403 Forbidden.
  - Teachers retain full access to all of their own documents across all processing states.

## 3. Teacher Voice Cloning Consent & Security

* **Context**: Voice cloning must be strictly consensual, transparent, and legally sound.
* **Decision**:
  - `VoiceProfile` records have two gates: `status == "active"` and `consent_confirmed == True`.
  - Student preference selection (`PUT /me/preferences`) strictly validates that any assigned `voice_profile_id` belongs to an active profile with confirmed consent; otherwise returning HTTP 400 Bad Request.
  - `GET /voices` lists only active profiles with confirmed consent.
  - Every playback generated using a cloned voice displays the mandatory transparency disclaimer:
    `"AI-generated voice, authorized by the teacher."`

## 4a. Gnani TTS model and voice pairing

* **Context**: Play produced only a beep because Mock TTS was selected, and a `timbre-v2.5` + `Shivani` pairing is rejected by Gnani (Shivani is Timbre v3.0-only).
* **Decision**: Default `TTS_PROVIDER=auto` uses Gnani when `GNANI_API_KEY` is set. Standard TTS uses `timbre-v3.0` + `Lakshmi` (documented e-learning voice). Real-provider failures return an error code/message; they never fall back to the mock beep. Mock audio is labelled in the UI.

## 4. TTS Fallback Architecture

* **Context**: External cloned voice synthesis APIs may experience rate limits, latency, or outages. A student studying should not be blocked from hearing answers.
* **Decision**:
  - If a teacher's cloned voice fails or is invalid, the backend automatically falls back to the default synthetic voice.
  - The API response signals `fallback = True` with a clear user notice (`"Teacher voice unavailable; used default voice."`).

## 5. Mock TTS Provider Selection & Transparency (Task 0 Decision)

* **Context**: Without a configured `GNANI_API_KEY`, real Gnani TTS cannot be used. Developers and testers need working audio synthesis during development.
* **Decision**:
  - `TTS_PROVIDER=auto` (default) selects real Gnani when `GNANI_API_KEY` is set, otherwise selects Mock.
  - Mock TTS generates a valid WAV file with a 440Hz tone (default voice) or 320Hz tone (cloned voice).
  - AudioPlayer shows a "🧪 mock audio (synthetic development tone)" badge when `isMock=true`.
  - Backend logs active providers at startup (STT, TTS, LLM, VoiceClone class names).
  - Real provider failures return explicit error codes (401/403/429/504/502) with non-secret error messages, never falling back to mock.
  - When `GNANI_API_KEY` is configured, TTS provider auto-switches to GnaniTimbreTTSService without code changes.

## 6. BUG FIXES (2026-11-14)

### Bug 3: TTS Endpoint Configuration
* **Issue**: Teacher audio failed with `TTS_NOT_CONFIGURED` ("Gnani Timbre endpoint is not configured") even though a default should exist.
* **Root Cause**: `GNANI_TIMBRE_ENDPOINT` defaulted to an empty string, and the service treated the resulting endpoint check as the failure instead of the genuinely-missing API key — so a missing key surfaced as an "endpoint not configured" error.
* **Verified against https://docs.gnani.ai/api/TTS/tts-inference** (no guessing):
  - Endpoint: `POST https://api.vachana.ai/api/v1/tts/inference`.
  - Headers: `X-API-Key-ID` (the API key) and `Content-Type: application/json`.
  - Body fields: `text`, `voice`, `model`, `language`, `speed`, `audio_config`.
  - Model/voice: `timbre-v3.0` with voice `Lakshmi` (a documented v3.0 voice); v3.0 voices speak all 10 supported languages.
  - `audio_config`: `encoding=linear_pcm`, `container=wav`, `num_channels=1`, `sample_width=2`, `sample_rate=24000` (24000 is an officially supported rate).
  - Output: a WAV file (`audio/wav`); `language` accepts `auto` and BCP-47 values such as `en-IN`, `hi-IN`, `kn-IN`.
* **Fix**:
  - `GNANI_TIMBRE_ENDPOINT` now defaults to `https://api.vachana.ai/api/v1/tts/inference` in settings, and the service also hard-falls-back to that URL, so it is never "not configured". A custom override via env is still honoured.
  - A missing API key is now a distinct, specific error (`TTS_API_KEY_MISSING`, HTTP 500) — separate from any endpoint concern, which cannot occur anymore.
  - Real provider failures (401/403, 402, 429, timeout, network, bad audio) map to explicit error codes and are returned to the UI; they are never replaced with a beep tone.
  - Cloned/teacher voice failure falls back to the default voice with a visible `notice`; if the default voice fails too, the explicit error is shown.
  - Startup logs the active STT, TTS, LLM, Embedding and VoiceClone providers with their config value and mock/real flag (no secrets).
  - Tests (`tests/backend/test_tts.py`): success (binary + JSON base64), missing key, 401/402/403/429, timeout, corrupt audio, endpoint default + override; `tests/backend/test_student_experience.py`: default voice, authorized cloned voice, and cloned→default fallback with notice.
  - Mock audio is labelled in the UI; the mock beep is only ever produced by the Mock provider, never as a fallback for a real failure.

### Bug 2: STT Language Code Mapping
* **Issue**: When speaking English, the transcript came back in Hindi.
* **Root Cause**: `normalize_language_code()` mapped the student's default ("auto"/unknown/empty) to a concrete `hi-IN`, and the mock provider echoed the raw input code back as the "detected" language instead of a normalized one. There was also no separate question-language selector in the UI, so the student could not tell the tutor which language they were actually speaking.
* **Fix**:
  - `LANGUAGE_CODE_MAP` verified against https://docs.gnani.ai/api/STT/speech-to-text (BCP-47, region uppercase). `auto`/`indic-auto`/"unknown"/"" now map to the documented auto-detect value `indic-auto` (`DEFAULT_LANGUAGE_CODE`), never to Hindi.
  - `as`/`as-IN` is not supported by `prisma-v3.0`, so it is routed through auto-detect (`indic-auto`) instead of being sent as an unsupported code.
  - `MockSTTService` and the Gnani service both return a concrete normalized/detected language code (`normalized` / `detected_language_code`), so the transcript response always shows the language actually used.
  - New dedicated **"I Will Speak In (Question Language)"** selector in `StudentDashboard.tsx` (default `indic-auto`), persisted via `PUT /me/preferences` `question_language` so the student's choice is remembered. `question_language` (STT) is kept separate from `answer_language` (LLM/TTS).
  - The transcript box now shows the detected language (`Detected language: <code>`).
  - Native scripts are preserved: Kannada→ಕನ್ನಡ, Hindi→हिन्दी, English→English (no transliteration).
  - Tests: backend `test_stt.py` (English never forced to Hindi, full language-code mapping table incl. empty/unknown, native-script preservation) and frontend `StudentExperience.test.tsx` (selector default = `indic-auto`, choice persisted).
* **Decision — "auto" default**: Because Gnani documents an auto-detect value (`indic-auto`), `auto` uses it rather than falling back to `en-IN`.


### Bug 1: RAG Grounding False Negatives (Question Not Found)
* **Issue**: Tutor says "not covered" for questions that are clearly in the notes.
* **Root Cause (confirmed)**: The legacy `PlaceholderEmbeddingService` produced 1536-dim vectors while the active `SentenceTransformerEmbeddingService` (e5-small) produces 384-dim. Any chunk indexed with the old model can never be compared with a new query vector, so its cosine similarity degrades to 0 and every question looks out of scope. The process also had no way to detect or repair stale chunks.
* **Fixes**:
  - **Active model is e5-small, 384-dim.** Documented as `EMBEDDING_DIMENSION = 384`; the service exposes `dimension`, `active_model_name` and `is_real_model` (mock vs real).
  - **e5 prefixes verified on both sides** — `embed_query` uses `"query: "`, `embed_passage`/`embed_texts(is_query=False)` use `"passage: "`.
  - **Dimension guard in `/ask`** — a stored chunk whose vector dimension differs from the query is skipped and counted (`dimension_mismatch_chunks`) instead of silently scoring 0.
  - **New `document_chunks.embedding_model` column** (Alembic 003 + idempotent `ALTER TABLE` in `main.py`) records the exact model used at ingest, so stale chunks are identifiable.
  - **Re-embed tooling** — `reembed_document_chunks()`, `reembed_all_chunks()`, `find_stale_documents()` in `document_processor.py`, plus the CLI `backend/scripts/reembed_chunks.py`. New uploads always stamp the currently-active model.
  - **Hybrid relevance** — `relevance = max(vector_cosine, lexical_overlap)` so a strong keyword match still grounds even when the vector score is low.
  - **Threshold** `SIMILARITY_THRESHOLD = 0.25` (lowered from 0.3 for short queries), configurable via env.
  - **`current_page` boost retained** (+0.2) but never raises an otherwise-zero match above an arbitrary floor.
  - **Scanned PDFs** fail loudly: "No extractable text found… OCR is not supported" instead of producing an empty-but-`ready` document.
  - **`RAG_DEBUG` env flag** returns a non-secret `debug` block (chunk ids, per-chunk vector/keyword scores, model, dimensions, candidate counts) and the student UI renders it in a collapsible "Debug (retrieval)" section only when enabled.
  - **Regression tests** in `tests/backend/test_ask.py`: answered-from-notes, genuinely-out-of-scope refused, re-embedded document becomes retrievable, embedding dimension/prefix guards, and debug block when `RAG_DEBUG` is on.
* **Decision — stale test file removed**: `tests/backend/test_multilingual_qa.py` imported a non-existent `app.services.rag_service` and referenced APIs (`EmbeddingService()`, `.generate(language=...)`) that never existed; it aborted the whole pytest collection. It was deleted; equivalent coverage now lives in `test_ask.py` against the real `/ask` endpoint.
* **Decision — raise default voice vs endpoint errors separately**: A missing API key and an unset endpoint are different misconfigurations and must produce different errors (see Bug 3).
* **Incidental production bug fixed**: `backend/app/api/voice_profiles.py` compared `user.role != UserRole.TEACHER`, but the enum members are lowercase (`teacher`/`student`). This raised `AttributeError` (HTTP 500) for every voice-cloning request. Corrected to `UserRole.teacher`.
