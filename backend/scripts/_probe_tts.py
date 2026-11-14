"""TEMPORARY diagnostic probe (delete before commit). Never prints the API key."""
import json
import sys
import time

import httpx

from app.core.config import settings

KEY = (settings.GNANI_API_KEY or "").strip()
ENDPOINT = settings.GNANI_TIMBRE_ENDPOINT
MODEL = settings.GNANI_TTS_MODEL
VOICE = settings.GNANI_TTS_VOICE

print(f"key_present={bool(KEY)} endpoint={ENDPOINT} model={MODEL} voice={VOICE}")

HEADERS = {"X-API-Key-ID": KEY, "Content-Type": "application/json"}


def call(label, payload):
    time.sleep(2.0)  # respect the "1 active request at a time" account limit
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.post(ENDPOINT, headers=HEADERS, json=payload)
    except Exception as e:  # noqa: BLE001
        print(f"[{label}] EXC {type(e).__name__}: {e}")
        return
    ct = r.headers.get("content-type", "")
    body = r.content[:200]
    try:
        shown = r.json()
    except Exception:
        shown = f"<{len(r.content)} bytes {ct}>"
    print(f"[{label}] {r.status_code} ct={ct} -> {shown}")


def cfg(rate=24000):
    return {"encoding": "linear_pcm", "container": "wav", "num_channels": 1,
            "sample_rate": rate, "sample_width": 2}


short = "What is photosynthesis, and how do plants make their food?"
long_text = ("Photosynthesis is the process by which green plants, algae and some "
             "bacteria convert light energy into chemical energy stored in glucose. ")
long_text = (long_text * 30)[:2600]

cases = [
    ("short/en-IN", {"text": short, "model": MODEL, "voice": VOICE, "language": "en-IN", "speed": 1.0, "audio_config": cfg()}),
    ("short/auto", {"text": short, "model": MODEL, "voice": VOICE, "language": "auto", "speed": 1.0, "audio_config": cfg()}),
    ("long/en-IN", {"text": long_text, "model": MODEL, "voice": VOICE, "language": "en-IN", "speed": 1.0, "audio_config": cfg()}),
    ("short/no-headers-json", {"text": short, "model": MODEL, "voice": VOICE, "language": "en-IN", "audio_config": cfg()}),
]

for label, payload in cases:
    call(label, payload)
