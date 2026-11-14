# Task 0: Fix TTS Beep Issue — Detailed Analysis

## Problem Statement
When students click "Play" on the audio response, they hear only a beep tone instead of the full synthesized speech answer. The audio is being generated but it's from the Mock TTS service (a synthetic 440Hz tone for default voice, 320Hz for cloned).

## Root Cause Analysis

### Current Behavior (Correct Design, but UX Issue)
1. Backend starts and checks `TTS_PROVIDER=auto` (default in config.py line 51)
2. `get_tts_service()` in tts_service.py (lines 356-376) selects:
   - Mock if pytest is detected OR `APP_ENV=test`
   - Mock if `TTS_PROVIDER=mock`
   - Gnani if `TTS_PROVIDER=gnani`
   - **Gnani if `TTS_PROVIDER=auto` AND `GNANI_API_KEY` is set**
   - **Mock otherwise** ← This is the issue
3. Since no `GNANI_API_KEY` is configured in backend/.env, Mock is always selected
4. MockTTSService.synthesize_speech() generates a 440Hz tone (default) or 320Hz (cloned)
5. AudioPlayer correctly marks it as `isMock=true` and shows "🧪 mock audio (synthetic development tone)"

### Why This Is Actually Correct Behavior
- The design is intentional: tests and dev without API keys use mock
- Mock audio is clearly labeled in UI
- Real failures never silently fall back to mock (per DECISIONS.md decision 4a)
- Error cases return proper error codes (401, 402, 403, 429, timeout, bad audio)

### The Real Issue: UX Expectation vs Reality
Users expect to hear real speech synthesis when they press Play. They need to:
1. Know the Mock TTS is active (already done with badge)
2. See a clear notice at startup showing which providers are active
3. Have real TTS working when an API key is configured
4. Never have silent failures

## Implementation Status

### ✅ Already Implemented (Correct)
- Mock TTS clearly labelled in UI (AudioPlayer lines 237-258)
- Startup logging of active providers (main.py lines 68-74)
- Real TTS failures return error codes (tts.py lines 106-117)
- No silent fallback to beep on real provider failure (tts.py lines 96-117)
- Comprehensive mocked tests for success/error scenarios (test_tts.py)

### ⚠️ Missing (To Complete Task 0)
1. Frontend test for mock audio badge visibility
2. Documentation: why mock is active (no API key configured)
3. Run full test suite to verify all cases work
4. Integration test: ask question → get answer → play audio

## Verification Checklist

### Backend Tests
- ✅ test_mock_tts_service_generates_valid_wav() — Mock generates WAV
- ✅ test_gnani_timbre_tts_success_binary() — Real call with binary audio
- ✅ test_gnani_timbre_tts_success_json_base64() — Real call with JSON base64
- ✅ test_gnani_cloned_tts_sends_speaker_embedding_object() — Cloned voice payload
- ✅ test_gnani_timbre_tts_401_403_authentication_error() — Auth error, no beep
- ✅ test_gnani_timbre_tts_403_scope_error() — Scope error
- ✅ test_gnani_timbre_tts_402_quota_error() — Quota error
- ✅ test_gnani_timbre_tts_429_rate_limit() — Rate limit error
- ✅ test_gnani_timbre_tts_timeout() — Timeout error
- ✅ test_gnani_timbre_tts_corrupt_bad_audio() — Bad audio error
- ✅ test_speak_endpoint_mock_voice_indicates_is_mock() — Mock badge in response
- ✅ test_speak_endpoint_real_tts_failure_does_not_beep() — Real failure returns error
- ✅ test_gnani_provider_without_key_does_not_beep() — No key → error, not beep

### Frontend Tests (To Add)
- [ ] AudioPlayer renders mock audio badge when isMock=true
- [ ] AudioPlayer shows error when audio blob decode fails
- [ ] AudioPlayer plays valid WAV data without errors

## Decision: What "Fix" Means

The code is already architecturally correct. The "fix" is:
1. **Confirm** all tests pass (TTS stack works correctly)
2. **Document** that Mock TTS is active because no API key is configured
3. **Add** frontend test for mock badge
4. **Verify** error handling doesn't silently beep
5. **Print** provider status on startup (already done)

When an actual `GNANI_API_KEY` is set in backend/.env:
- TTS provider will switch to GnaniTimbreTTSService automatically
- Real speech synthesis will be used
- "Mock audio" badge disappears, replaced with cloned/default voice labels as appropriate
- All error codes remain the same

## Notes for Deployment
- Leave `TTS_PROVIDER=auto` (default) for production
- Set `GNANI_API_KEY` in backend/.env when real Gnani account is available
- Mock TTS in dev/test is intentional and correct
- No secrets should appear in logs or error messages (verified in tts_service.py)
