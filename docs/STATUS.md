# ShikshaSaathi Voice — status

Bug fixes and the teacher voice-cloning feature are implemented, tested (mocked, no real
network calls) and committed.

| Item | Status | Commit |
|------|--------|--------|
| Bug 1 — RAG says "not covered" for covered questions | Done | `2534949` |
| Bug 2 — English speech transcribed as Hindi | Done | `aa5b1c2` |
| Bug 3 — `TTS_NOT_CONFIGURED` teacher audio | Done | `ed662dc` |
| Bug 4 — Non-English questions always refused | Done | `f2fa86d` |
| Bug 5 — Non-English output audio failed (TTS HTTP 500) | Done | `c4695a3` |
| Bug 6 — Latest-answer-only study UI (no conversation log) | Done | `e1bbe3d` |
| Feature — Teacher voice cloning (Gnani Vachana) | Done | (this commit) |

## Test results (last run)

- Backend: `python -m pytest tests/backend -q` → **125 passed**.
- Frontend: `npm run build` → exit 0 (only the pre-existing pdfjs `eval` and chunk-size warnings).
- Frontend unit tests: `npx vitest run` → **13 passed** (2 files).

## BUG 1 — RAG grounding false negatives

**Root cause**: the legacy placeholder embedding service produced 1536-dim vectors while
the active e5-small model produces 384-dim vectors, so any chunk indexed with the old
model could never be compared with a new query and every question looked out of scope.

**Fix**: dimension guard in `/ask` + `embedding_model` column + re-embed tooling +
`max(vector, keyword)` hybrid relevance + `SIMILARITY_THRESHOLD=0.25` + `RAG_DEBUG`
debug block (chunk ids and scores) shown in the UI only when enabled.

## BUG 2 — English speech transcribed as Hindi

**Root cause**: `normalize_language_code()` mapped the student default (`auto` / unknown /
empty) to a concrete `hi-IN`; the STT response also echoed the raw code instead of a
normalized one, and there was no question-language selector in the UI.

**Fix**: `auto`/unknown/empty now map to the documented auto-detect value `indic-auto`;
both providers return a concrete normalized/detected language; a dedicated
"I Will Speak In (Question Language)" selector (default `indic-auto`) is persisted via
`/me/preferences question_language`; the detected language is shown next to the transcript;
native scripts are preserved.

## BUG 3 — `TTS_NOT_CONFIGURED` teacher audio

**Root cause**: `GNANI_TIMBRE_ENDPOINT` defaulted to empty and the resulting check
surfaced as "endpoint is not configured", so a missing API key was reported as an endpoint
problem.

**Fix**: endpoint defaults to the documented `https://api.vachana.ai/api/v1/tts/inference`
(settings default + service fallback; env override still works); a missing key is a distinct
`TTS_API_KEY_MISSING` (500); real provider failures return explicit error codes (never a
beep); cloned-voice failure falls back to the default voice with a visible notice; startup
logs the active STT/TTS/LLM/Embedding/VoiceClone providers (mock vs real).

## BUG 4 — Non-English questions always refused ("not covered")

**Root cause (confirmed with `backend/scripts/debug_retrieval.py`)**: matching used cosine
similarity between the *original* question and English chunks, and a fixed
`SIMILARITY_THRESHOLD` alone decided refusal. A non-English question has no lexical overlap
with English chunks and its cross-lingual score falls below the old floor, so it was always
dropped and refused. Measured on the same notes (`jesc110-min.pdf`): English top score
`1.0000` vs Hindi-only top score `0.1043`.

**Fix**: non-English questions are rewritten into English by the LLM (`LLMService.rewrite_query`)
and retrieved with **both** phrasings, merging the best score per chunk; the threshold is now
a *lenient floor* (`0.10`) that never decides refusal alone (rank-based fallback keeps the
best chunk); `grounded=false` is set **only** when the LLM replies with `NOT_IN_STUDY_MATERIAL`;
e5 prefixes (`query: ` / `passage: `) confirmed; the prompt carries the question language and
the requested answer language (instructions stay English); `RAG_DEBUG` returns retrieved chunk
ids and scores. Debug tool: `python backend/scripts/debug_retrieval.py "<question>"`.

## BUG 5 — Non-English output audio failed (TTS HTTP 500)

**Root cause**: the answer-language selector submits BCP-47 codes (`hi-IN`, `kn-IN`, …), but
`GnaniTimbreTTSService._normalize_language` lower-cased them and sent the undocumented `hi-in`
to Gnani, which replies with a generic HTTP 500 ("We are facing technical difficulties").
English (`en` → `en-IN`) worked, which is why only non-English failed.

**Fix**: normalize to documented Gnani codes (region casing preserved: `hi-IN` stays `hi-IN`;
short codes expanded: `hi` → `hi-IN`), fall back to script auto-detection (`auto`) for codes
Gnani cannot speak (e.g. Assamese), and retry once with `auto` if Gnani still returns HTTP 500
— so audio is produced in the language of the answer's script.

## FEATURE — Teacher voice cloning (Gnani Vachana)

Teachers can clone their own voice from a short recording; students can then hear answers in
that teacher's cloned voice in the study page.

**Flow / contract (verified against https://docs.gnani.ai Voice Cloning pages):**

1. Reference audio → `POST https://api.vachana.ai/api/v1/tts/voice-clone/embeddings`
   (header `X-API-Key-ID`, multipart field `audio_file`, clean WAV/MP3, 5–30 s). The response
   returns a **speaker embedding** (`data.voice_clone_embedding.{embedding,shape,dtype}`), not
   an opaque voice id. We store that embedding JSON as `VoiceProfile.gnani_voice_id`.
2. Cloned synthesis → the existing `GnaniTimbreTTSService` REST call
   `POST https://api.vachana.ai/api/v1/tts/inference` with model `vachana-vc-v1` and the stored
   `speaker_embedding`. This is a plain REST call (no SSE), so the backend returns a single audio
   blob — no stream assembly needed.
3. There is **no documented voice-delete endpoint**, so `delete_voice` is a best-effort no-op
   (recorded in DECISIONS 7b); revoking/deleting a profile only removes it on our side.

**Backend**

- `VoiceCloneService` interface (`create_voice`, `synthesize_with_cloned_voice`, `delete_voice`,
  `is_mock`) with `MockVoiceCloneService` and `GnaniVoiceCloneService`, selected by
  `VOICE_CLONE_PROVIDER` (default `auto`: real when `GNANI_API_KEY` is set, else mock; tests
  always get the mock).
- `VoiceConsent` table (Alembic `004_voice_clone`): teacher_id, consent_text_version, full
  consent text, confirmed, IP, user agent, revoked_at/revoke_reason, timestamps.
- `VoiceProfile`: teacher_id, voice_name, `gnani_voice_id` (embedding JSON), languages, status
  (`pending`/`active`/`failed`/`revoked`), consent_confirmed, sample path, timestamps.
- Teacher-only endpoints: `GET /voice-profiles/consent`, `POST /voice-profiles`
  (multipart file + name + `consent_confirmed=true`; rejects without consent, validates duration
  5–30 s, size and type, converts WebM→WAV), `GET /voice-profiles` (own only),
  `POST /voice-profiles/{id}/preview`, `POST /voice-profiles/{id}/revoke`,
  `DELETE /voice-profiles/{id}`. Students get 403; a teacher only ever sees their own profiles.
- A profile becomes **active only through the consent flow**; the old bypass that set
  `consent_confirmed` was removed. `/me/preferences` accepts a `voice_profile_id` only if it is
  an active, non-revoked, consent-confirmed profile.
- Rate limits: profile creation and preview are limited per teacher
  (`VOICE_CLONE_CREATE_RATE_LIMIT` / `VOICE_CLONE_PREVIEW_RATE_LIMIT` within
  `VOICE_CLONE_RATE_WINDOW_SECONDS`) and profiles are capped at `VOICE_CLONE_MAX_PROFILES` (3).
- `/voices` lists only active profiles with confirmed, non-revoked consent; `/tts/speak` uses the
  cloned voice when `voice_profile_id` is set, returns label
  `"AI-generated voice, authorized by the teacher."` and, if the clone fails, plays the default
  voice with `fallback=true` + a notice — it **never** substitutes a beep.

**Frontend**

- Teacher dashboard → "🎙️ My Voice": consent statement + a tick box that cannot be skipped,
  record with `MediaRecorder` (timer, level meter, auto-stop at 30 s, re-encoded to 16 kHz WAV),
  or upload WAV/MP3; playback before submitting; suggested 20–30 s reading script + clean-recording
  tips; profile list with status badges, Preview / Revoke / Delete (with confirmation) and clear
  per-failure error messages.
- Student study page: the "Choose teacher voice" step and the header voice pill list each
  teacher's active cloned voice by name plus a "🔊 Sample" preview button (and Default voice);
  cloned playback always shows the disclosure label; a fallback notice appears when the default
  voice was used; the choice is saved via `/me/preferences`.

### What is real vs mocked

| Piece | Status |
|-------|--------|
| Consent capture, validation, DB writes, role/isolation/cap/rate-limit checks | **Real** |
| Cloned-voice playback wiring, disclosure label, fallback-with-notice | **Real** |
| Gnani embeddings + cloned-TTS HTTP contract (URLs, headers, model, payload) | **Real (documented contract)** |
| Network calls to Gnani during tests | **Mocked** (tests never hit the network) |
| Voice provider when `VOICE_CLONE_PROVIDER=mock`, or `auto` with no `GNANI_API_KEY` | **Mock** (synthesises a 320 Hz tone labelled "🧪 mock audio"; delete + re-create after switching to the real provider) |
| Provider voice deletion | **Not available** — best-effort no-op (no documented endpoint) |

## Manual verification

See `docs/MANUAL_TEST_CHECKLIST.md` for step-by-step checks.

## Notes / caveats

- Tests run with the system Python (`python -m pytest`); the repo `.venv` is empty.
- Test infra forces mocks (`APP_ENV=test`); no test makes a real network call.
- `frontend/dist` build artifacts are generated by `npm run build`.
- No secret values are read, printed, logged or committed; only `.env.example` is edited.

## Remaining work

None — all bug fixes and the teacher voice-cloning feature are complete. See
`docs/BLOCKERS.md` for the (unconfirmed) account-level gating note about Gnani voice cloning.
