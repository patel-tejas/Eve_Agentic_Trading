"""Per-user, per-tier token buckets for the common gate (Phase 15, P0).

In-process and in-memory: one bridge process serves one Hisaab deployment.
If the bridge is ever scaled horizontally this moves to a shared store; the
interface stays the same.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    """``allow(key, tier, per_minute)`` -> (allowed, retry_after_seconds)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, tier: str, per_minute: int) -> tuple[bool, float]:
        if per_minute <= 0:
            return False, 60.0
        capacity = float(per_minute)
        refill_per_s = per_minute / 60.0
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get((key, tier), (capacity, now))
            tokens = min(capacity, tokens + (now - last) * refill_per_s)
            if tokens >= 1.0:
                self._buckets[(key, tier)] = (tokens - 1.0, now)
                return True, 0.0
            self._buckets[(key, tier)] = (tokens, now)
            return False, (1.0 - tokens) / refill_per_s

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
