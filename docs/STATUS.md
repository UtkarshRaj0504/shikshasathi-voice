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
| Bug 7 — Voice-clone preview played a beep (mock used by default) | Done | `ed05314` |
| Bug 8 — `POST /voice-profiles` failed with an opaque HTTP 400 ("not cloning") | Done | `f3e7c3f` |
| Bug 9 — `VOICE_CLONE_PROVIDER_ERROR` (Gnani embeddings HTTP 500 not retried) | Done | `c544f81` |
| Bug 10 — same HTTP 500 persisted: browser WebM/Opus audio sent to the provider | Done | `7ea77dc` |
| Bug 11 — `TTS_RATE_LIMIT` (Gnani HTTP 429 not retried) + aliased in-browser downsample | Done | `ede919b` |
| Feature — Teacher voice cloning (Gnani Vachana) | Done | `e43f81c` |

## Test results (last run)

- Backend: `python -m pytest tests/backend -q` → **134 passed**.
- Frontend: `npm run build` → exit 0 (only the pre-existing pdfjs `eval` and chunk-size warnings).
- Frontend unit tests: `npx vitest run` → **13 passed** (2 files).

## BUG 8 — creating a voice profile returned HTTP 400

**Symptom**: `POST /voice-profiles` → `400 Bad Request`; the pasted server log ended at the
profile-cap `count(*)` query, then `ROLLBACK` — i.e. **no provider call and no row written**,
so the request died inside a pre-provider guard.

**Root cause**: the cap counted every non-`revoked` profile, including the `failed` row that
each rejected attempt writes. A few retries therefore silently used up all
`VOICE_CLONE_MAX_PROFILES` slots while the teacher still had no usable voice, and the next
attempt was refused with a bare `PROFILE_LIMIT_REACHED` — with nothing logged to explain it.
The UI also never reloaded the list after a failed create, so it never showed those rows.

**Fix**: the cap now counts only **usable** profiles (`active`/`pending`) in both the API and
the page; the page reloads the list after a failed attempt; the two pre-provider `400`s are
logged with their reason; the recorder auto-stops at 25 s (margin under the provider's 30 s
hard limit) and *Create* is disabled for a recording shorter than 5 s. See
`docs/DECISIONS.md` §7i-7j. The original provider error (e.g. `VOICE_CLONE_FORBIDDEN` when
Gnani has not enabled cloning for the account) now surfaces on every retry instead of being
masked by a limit error — see `docs/BLOCKERS.md`.

## BUG 9 — `VOICE_CLONE_PROVIDER_ERROR: Voice cloning failed (HTTP 500)`

**Symptom**: with the Bug 8 cap mask gone, the real provider error surfaced:
`VOICE_CLONE_PROVIDER_ERROR: Voice cloning failed (HTTP 500).` — Gnani's voice-clone
*embeddings* endpoint (`POST /api/v1/tts/voice-clone/embeddings`) answered HTTP 500.

**Root cause** (per https://docs.gnani.ai/api/introduction/errors): HTTP 500 on the embeddings
endpoint is an "unexpected failure" — which the docs note can include reference audio it cannot
process — and **`429/500/503/504` are documented as retryable with exponential backoff**; we
called the endpoint exactly once and gave up on the first 500. The error body was also mishandled:
Voice Cloning (like TTS) returns a **flat** body `{"success": false, "message": ..., "status_code": N}`,
but the `>=400` fallback kept only the raw text and never used the provider's own `message`, so
the UI showed a bare "HTTP 500" with no explanation.

**Fix**: `GnaniVoiceCloneService._post_embeddings` now retries `429/500/503/504` with exponential
backoff (0.5 s, 1 s; up to 3 attempts) before raising, and a new `_body_message` extracts the
provider's message from the flat body (and the gateway `detail` / `422 detail[]` shapes), so the
real reason reaches the UI on the final failure. The Step-2 cloned-synthesis path already sends
the REQUIRED `audio_config` and surfaces the provider body, so no change was needed there. See
`docs/DECISIONS.md` §7k. Two tests were added (500-then-200 retries to success; a persistent 500
surfaces the provider message). Retrying and reporting the message made the error clearer, but the
500 **still happened on every attempt** — the real cause was the uploaded bytes (Bug 10).

## BUG 10 — the same HTTP 500 persisted: browser WebM/Opus was sent to the provider

**Symptom**: after Bug 9, creating a voice profile still failed every time with
`VOICE_CLONE_PROVIDER_ERROR: Voice cloning failed (HTTP 500). We are facing technical difficulties.
Please try again later.` (the message now came from Gnani's own body, but the 500 never went away).

**Root cause** (confirmed by a live probe against the real endpoint): the browser's `MediaRecorder`
records **WebM/Opus**, and the client-side `blobToWav` helper silently returned the *original* blob
whenever `AudioContext.decodeAudioData` failed. Gnani **cannot decode WebM** and answers with the
generic HTTP 500 above; the exact same audio transcoded to WAV returned HTTP 200 with an embedding.
Probe evidence: raw WebM → `500 {"message":"We are facing technical difficulties."}`, decoded WAV →
`200 {"success":true,...}`.

**Fix**: `app/services/audio_utils.py` now has `normalize_reference_audio()`, which decodes whatever
the browser produced with **PyAV** (bundled FFmpeg — already a declared dependency) and re-encodes it
as **16 kHz mono 16-bit WAV** before the provider call; undecodable bytes raise a clear
`INVALID_AUDIO` (HTTP 400) instead of reaching the provider as an opaque 500. Duration is now checked
on the **decoded** audio (the old byte-size estimate wrongly rejected short-but-valid WebM/Opus
clips). `POST /voice-profiles` calls this right after `validate_reference_audio()` and always sends
the provider a `sample.wav`. See `docs/DECISIONS.md` §7l. Three tests were added (normalized output is
16 kHz mono WAV; undecodable bytes raise; a real WebM/Opus upload creates an active profile).

## BUG 11 — `TTS_RATE_LIMIT: Gnani TTS rate limit exceeded` (no output audio)

**Symptom**: the student spoke a question, got a transcript back, but heard no audio; the UI
showed `TTS_RATE_LIMIT: Gnani TTS rate limit exceeded. Please try again in a minute.` — Gnani
answered the TTS call with HTTP **429**.

**Root cause** (docs + code): Gnani limits the account to **one active request at a time**, so a
429 means "a request was still running", not "you are out of quota"; the docs explicitly say the
429 carries **no `Retry-After` header** and must be answered by *waiting and retrying with
backoff* (`429/500/503/504`). `GnaniTimbreTTSService.synthesize_speech()` treated the very first
429 as terminal and raised, so any transient collision (the voice flow also makes a cloned-voice
attempt before the default-voice call) surfaced as a hard failure with no audio.

**Fix**:
- `GnaniTimbreTTSService` now retries `429/500/503/504` with exponential backoff
  (`0.5 s, 1 s, 2 s`; 4 attempts total), honouring `Retry-After` when the provider does send it
  (capped at 8 s). The existing "HTTP 500 → retry once with `language=auto`" behaviour is kept and
  composes with the new loop. Decisions: `docs/DECISIONS.md` §7m.
- The student recorder no longer decimates 48 kHz → 16 kHz with a **filterless box average**
  (which aliases). It sends the device-rate WAV and the backend resamples it to 16 kHz mono with
  PyAV's anti-aliased polyphase resampler (`convert_audio_to_wav`), so the speech the provider
  hears is a faithful, properly band-limited 16 kHz stream. Decision: §7n.
- Five tests were added/updated: a transient 429 retries then succeeds; a 503 retries then
  succeeds; a persistent 429 exhausts the attempts and still surfaces `TTS_RATE_LIMIT`; the
  backoff honours `Retry-After` and otherwise doubles from 0.5 s.

**Not changed (evidence)**: live probes (`indic-auto`, `en-IN`, `hi-IN`) on clean English speech
all returned an **`en-IN`** transcript, and the same probe through the old box downsampler still
returned `en-IN` — so the "English heard as Hindi" report is not caused by the language-code
mapping (Bug 2) nor by a hard decoder bug. `language_code` is documented as a **hint**: the model
detects from the audio. The guaranteed path for an English question remains the explicit
**"English"** choice in the *I Will Speak In* selector; the ambiguous Indian-English case with
`indic-auto` is the provider's detection. See §7n/§7o in `docs/DECISIONS.md`.

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
  `VOICE_CLONE_RATE_WINDOW_SECONDS`) and each teacher is capped at `VOICE_CLONE_MAX_PROFILES` (3)
  **usable** profiles — `failed`/`revoked` rows never consume a slot.
- `/voices` lists only active profiles with confirmed, non-revoked consent; `/tts/speak` uses the
  cloned voice when `voice_profile_id` is set, returns label
  `"AI-generated voice, authorized by the teacher."` and, if the clone fails, plays the default
  voice with `fallback=true` + a notice — it **never** substitutes a beep.

**Frontend**

- Teacher dashboard → "🎙️ My Voice": consent statement + a tick box that cannot be skipped,
  record with `MediaRecorder` (timer, level meter, auto-stop at 25 s, re-encoded to 16 kHz WAV),
  or upload WAV/MP3; playback before submitting; suggested reading script + clean-recording
  tips; profile list with status badges, Preview / Revoke / Delete (with confirmation) and clear
  per-failure error messages. *Create* stays disabled until the consent box is ticked, a sample
  of at least 5 s is ready, a name is typed and a profile slot is free; the list is reloaded
  after every attempt so a `failed` row is never hidden.
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
