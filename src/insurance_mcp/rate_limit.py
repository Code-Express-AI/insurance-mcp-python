"""A small per-caller rate limiter, kept in memory.

Memory is per process: two server processes would each count separately.
That's fine for one process. More would need a shared store such as Redis.
"""

import math
import time
from collections import defaultdict, deque


class RateLimiter:
    """Allows at most `limit` hits per key in any `window_seconds` (a sliding window)."""

    def __init__(self, limit: int, window_seconds: int, clock=time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        # Tests pass a fake clock, so they don't have to wait a real minute.
        self.clock = clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> int | None:
        """Count one hit for `key`.

        Returns None if it's allowed, or the seconds to wait if it isn't.
        A hit that isn't allowed isn't counted.
        """
        now = self.clock()
        hits = self.hits[key]
        # Forget hits that have dropped out of the window.
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()

        if len(hits) >= self.limit:
            # The oldest hit leaves the window first, and frees a place.
            return math.ceil(hits[0] + self.window_seconds - now)

        hits.append(now)
        return None
