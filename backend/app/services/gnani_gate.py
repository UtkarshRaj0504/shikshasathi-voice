"""Shared single-slot gate for Gnani API calls.

The Gnani account permits only ONE active request at a time across *all* of its
services, so speech-to-text and text-to-speech contend for the same slot. A voice
question sent while the previous answer is still being synthesised was rejected
by Gnani with HTTP 429 ("Gnani API rate limit exceeded").

Both services now funnel their provider calls through this one gate, so a request
waits for the slot instead of colliding with an in-flight request from the other
service.
"""

import asyncio
import threading

#: Seconds a caller waits for the single Gnani slot before giving up.
GNANI_SLOT_TIMEOUT_SECONDS = 180.0

#: The one Gnani slot. A ``threading.Lock`` (not ``asyncio.Lock``) because the
#: synchronous TTS path acquires it from a thread-pool worker, where no event
#: loop is available.
_SLOT = threading.Lock()


class GnaniSlot:
    """Owns the single Gnani slot for the duration of a ``with``/``async with``.

    Both entry points return ``True`` when the slot was acquired and ``False``
    when the wait timed out; callers must check the flag before contacting Gnani.
    """

    def __enter__(self) -> bool:
        self._acquired = _SLOT.acquire(timeout=GNANI_SLOT_TIMEOUT_SECONDS)
        return self._acquired

    def __exit__(self, *exc_info) -> None:
        if self._acquired:
            _SLOT.release()

    async def __aenter__(self) -> bool:
        # Wait off the event loop so a busy slot never stalls unrelated requests.
        self._acquired = await asyncio.to_thread(
            _SLOT.acquire, True, GNANI_SLOT_TIMEOUT_SECONDS
        )
        return self._acquired

    async def __aexit__(self, *exc_info) -> None:
        if self._acquired:
            _SLOT.release()
