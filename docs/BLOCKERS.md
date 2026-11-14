# Known Blockers & Constraints

## No Blockers Currently
All tasks can proceed with current access levels.

## Voice Cloning — possible account-level gating (unconfirmed)
Voice cloning calls were **not** exercised against the live Gnani account (tests are fully
mocked and never touch the network), so we cannot confirm from here whether cloning is enabled
on this account. The code path is in place and the Mock provider works end to end regardless.

If the account does **not** have voice cloning enabled, `POST /voice-profiles` (and
`POST /voice-profiles/{id}/preview`) fail with:

- HTTP `403` and error code `VOICE_CLONE_FORBIDDEN`
  (mapped from Gnani's gateway envelope `{"detail":{"error_code":...,"message":...}}`;
  the raw status is 403). Related mappings: `401 → VOICE_CLONE_AUTH` (bad/missing key),
  `402 → VOICE_CLONE_QUOTA` (no credit), `429 → VOICE_CLONE_RATE_LIMIT`,
  `400/422 → VOICE_CLONE_BAD_AUDIO`, timeout → `504`, network error → `502`.

The reference-audio upload endpoint is
`POST https://api.vachana.ai/api/v1/tts/voice-clone/embeddings` (header `X-API-Key-ID`).

What to ask Gnani support to confirm/enable:
1. Is **voice cloning** (`voice-clone/embeddings` + `vachana-vc-v1` synthesis) enabled for my
   account and API key? Please enable it if not.
2. Does the key have the required scope/plan for cloning (it may be a separate entitlement from
   standard TTS)?
3. Which languages and audio formats are supported for the reference clip
   (docs say clean WAV/MP3, ideally 5–30 s)?
4. Is there a documented endpoint to **delete** a cloned voice/embedding? (None is documented, so
   our delete is currently a best-effort no-op.)

Until it is enabled, run with `VOICE_CLONE_PROVIDER=mock` (auto-detected only when
`GNANI_API_KEY` is empty — see DECISIONS.md 7h) so cloning works end to end with a labelled
synthetic tone.

**Note (Bug 8)**: while the account is rejecting cloning, every attempt stores a `failed`
profile. Those rows used to count toward `VOICE_CLONE_MAX_PROFILES`, so after a few retries the
teacher was refused with a bare `HTTP 400 PROFILE_LIMIT_REACHED` — which *looked* like "cloning
is broken" while hiding the real `VOICE_CLONE_FORBIDDEN`/`VOICE_CLONE_AUTH` cause. Failed rows
no longer consume a slot, so the provider's actual error is now what the teacher sees on every
retry. If `POST /voice-profiles` fails, read the error code in the response/UI first — a
`PROFILE_LIMIT_REACHED` means the cap (delete a profile), while `VOICE_CLONE_*` points at the
provider/account.

### Previously Resolved
- ✅ TTS mock vs real provider selection (fixed in DECISIONS.md decision 4a)
- ✅ Voice model/voice pairing (timbre-v3.0 + Lakshmi documented)
- ✅ VoiceProfile consent gates (two-gate model: status + consent_confirmed)

## Notes for Gnani Account Issues
When testing against the real Gnani API:
- API Key: stored in backend/.env as GNANI_API_KEY (never committed)
- Rate limits: 429 errors handled gracefully
- Voice model compatibility: timbre-v3.0 for standard, vachana-vc-v1 for cloned
- Endpoint documentation: https://docs.gnani.ai (verify before release)

## Development Environment
- Python 3.11+ venv setup may require manual wheel installation on Windows
- pgvector requires PostgreSQL with pgvector extension (development uses SQLite mock)
- Frontend build and tests require Node 18+ and npm 9+
