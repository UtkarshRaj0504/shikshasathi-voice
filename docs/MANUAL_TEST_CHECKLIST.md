# Manual Test Checklist — Bug Fixes

Run the backend once without secrets in the environment so provider behaviour is
obvious. `.env.example` lists every variable; do **not** commit a real `.env`.

Quick automated checks:

```
python -m pytest tests/backend -q      # expect: 100 passed
cd frontend ; npm run build            # expect: exit 0
cd frontend ; npx vitest run           # expect: 7 passed
```

---

## BUG 1 — Tutor says "not covered" for covered questions

### How to verify by hand
1. Start the backend (it prints the active providers and warns about stale chunks).
2. If it warns that some documents were indexed with a different embedding model, run
   `python backend/scripts/reembed_chunks.py` (prints the active model + stale docs and
   re-embeds them). New uploads always use the active model automatically.
3. As a teacher, upload a small text/PDF document (3–5 pages) into a chapter and wait for
   status `ready`.
4. Set `RAG_DEBUG=true` in the backend environment and restart.
5. As a student, open that chapter and ask (in **English**) a question the document clearly
   answers, e.g. "What is photosynthesis?".
   - Expect: a grounded answer, and a green "Grounded in Study Material" banner.
   - Expand the "🐞 Debug (retrieval)" section: check `Model` is the e5-small model, `Query
     dim` is 384, `Dim mismatch` is 0, and the matched chunk has a score above the threshold.
6. Ask a genuinely out-of-scope question, e.g. "What is a quantum computer?".
   - Expect: the "isn't covered in the uploaded material" notice, and the debug list shows
     all candidate scores below the threshold.
7. Set `RAG_DEBUG=false` and restart: the debug section must disappear.

### Pass criteria
- In-scope questions are grounded; out-of-scope questions are refused.
- Debug block appears only when `RAG_DEBUG=true` and shows chunk ids + scores.

---

## BUG 2 — English speech transcribed as Hindi

### How to verify by hand
1. As a student, open a chapter's study reader.
2. In "I Will Speak In (Question Language)", the default is **Auto-detect (match my voice)**.
3. Set it to **English**, click "Ask Question", and speak an English question.
   - Expect: the transcript box is English (Latin script), and next to the label you see
     `Detected language: en-IN`.
4. Set it to **Hindi** and speak Hindi → transcript in Devanagari, `Detected language: hi-IN`.
5. Set it to **Kannada** and speak Kannada → transcript in Kannada script, `Detected language: kn-IN`.
6. Reload the page: the selector must remember your last choice (persisted via
   `/me/preferences question_language`).

### Pass criteria
- English never comes back as Hindi; native scripts are preserved (no transliteration).
- The detected language is shown; the choice survives a reload.

---

## BUG 3 — Teacher audio: `TTS_NOT_CONFIGURED`

### How to verify by hand
1. Start the backend **without** `GNANI_API_KEY`. At startup you should see a block like:
   ```
   STT:        MockSTTService (config: auto, mock: True)
   TTS:        MockTTSService (config: auto, mock: True)
   LLM:        ... 
   Embedding:  intfloat/multilingual-e5-small (real: <bool>, dim: 384)
   VoiceClone: ...
   ```
   Misconfiguration is obvious from this block.
2. As a student, ask a question with **no** voice profile selected → you get mock audio,
   labelled "🧪 mock audio (synthetic development tone)". (Mock is expected with no key.)
3. Force the real provider with a dummy key and no credits to see the error path:
   set `GNANI_API_KEY=test-dummy` and `TTS_PROVIDER=gnani`, restart, then ask a question.
   - Expect: a clear error in the UI (e.g. `TTS_API_KEY_MISSING` / `TTS_AUTH: ...`), **never**
     a beep tone.
   - The endpoint itself is never reported as "not configured" — with no env override it
     defaults to `https://api.vachana.ai/api/v1/tts/inference`.
4. Select an authorized teacher (cloned) voice; if the clone synthesis fails you should see
   the default voice play with a visible notice "Teacher voice unavailable (...); used default
   voice." If the default voice also fails, the explicit error is shown instead.

### Pass criteria
- Missing key → specific `TTS_API_KEY_MISSING` error, not an endpoint error.
- A real-provider failure is surfaced as an error, never replaced by a beep.
- Cloned-voice failure falls back to the default voice with a visible notice.
- Startup prints active STT/TTS/LLM/Embedding/VoiceClone providers and their mock/real state.

---

## Regression tests added

| Test | Bug | Verifies |
|------|-----|----------|
| `test_ask.py::test_ask_answered_from_notes` | 1 | Question answered from the notes |
| `test_ask.py::test_ask_out_of_scope_question_refused` | 1 | Out-of-scope question refused |
| `test_ask.py::test_ask_reembedded_document_becomes_retrievable` | 1 | Re-embedded document retrievable |
| `test_ask.py::test_ask_returns_debug_when_rag_debug_enabled` | 1 | `RAG_DEBUG` debug block |
| `test_ask.py::test_embedding_dimension_is_384` / `..._applies_e5_prefixes` | 1 | Model dim + e5 prefixes |
| `test_stt.py::test_stt_transcribe_english_is_never_forced_to_hindi` | 2 | English stays English |
| `test_stt.py::test_stt_language_code_mapping` | 2 | en/hi/kn/auto/unknown mapping |
| `test_stt.py::test_stt_transcript_preserves_native_script` | 2 | Native scripts kept |
| `StudentExperience.test.tsx` (question-language selector) | 2 | Selector default + persistence |
| `test_tts.py` (success/missing key/401/402/403/429/timeout/corrupt/endpoint default) | 3 | TTS error + endpoint behaviour |
| `test_student_experience.py::test_tts_speak_fallback_when_voice_fails` | 3 | Cloned→default fallback with notice |
