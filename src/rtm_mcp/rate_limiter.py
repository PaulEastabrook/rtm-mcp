"""Token bucket rate limiter and request statistics for RTM API."""

import asyncio
import time
from collections import deque


class TokenBucket:
    """Token bucket rate limiter matching RTM's burst and sustained rate limits.

    Pre-filled to capacity on construction so the first `capacity` requests
    fire immediately.  After that, tokens refill at `refill_rate` per second.
    """

    def __init__(self, capacity: int = 3, refill_rate: float = 0.9) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()
        self._paused_until: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Consume one token, waiting if necessary."""
        while True:
            async with self._lock:
                self._refill()
                now = time.monotonic()
                if now < self._paused_until:
                    wait = self._paused_until - now
                elif self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                else:
                    wait = (1.0 - self._tokens) / self.refill_rate
            # Sleep outside the lock so other callers aren't blocked
            await asyncio.sleep(wait)

    def pause(self, seconds: float) -> None:
        """Pause the bucket for *seconds* (called on HTTP 503).

        Drains remaining tokens and delays the next refill, forcing all
        callers to back off.
        """
        self._tokens = 0.0
        self._paused_until = time.monotonic() + seconds

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    @property
    def tokens_available(self) -> float:
        """Approximate token count (no lock, for diagnostics only)."""
        elapsed = time.monotonic() - self._last_refill
        return min(self.capacity, self._tokens + elapsed * self.refill_rate)


class RateLimitStats:
    """Rolling-window request statistics for diagnostics."""

    def __init__(self) -> None:
        self._request_timestamps: deque[float] = deque()
        self._retry_timestamps: deque[float] = deque()
        self._conn_retry_timestamps: deque[float] = deque()
        self._http_503_count: int = 0

    def record_request(self, request_type: str = "read") -> None:
        """Record an API request."""
        self._request_timestamps.append(time.monotonic())

    def record_retry(self) -> None:
        """Record a retry attempt."""
        self._retry_timestamps.append(time.monotonic())

    def record_conn_retry(self) -> None:
        """Record a connection retry attempt."""
        self._conn_retry_timestamps.append(time.monotonic())

    def record_503(self) -> None:
        """Record an HTTP 503 response."""
        self._http_503_count += 1

    def requests_last_60s(self) -> int:
        """Number of requests in the last 60 seconds."""
        return self._count_in_window(self._request_timestamps)

    def retries_last_60s(self) -> int:
        """Number of retries in the last 60 seconds."""
        return self._count_in_window(self._retry_timestamps)

    def conn_retries_last_60s(self) -> int:
        """Number of connection retries in the last 60 seconds."""
        return self._count_in_window(self._conn_retry_timestamps)

    @property
    def http_503_count_session(self) -> int:
        """Total HTTP 503 responses this session."""
        return self._http_503_count

    @staticmethod
    def _count_in_window(timestamps: deque[float], window: float = 60.0) -> int:
        cutoff = time.monotonic() - window
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        return len(timestamps)
