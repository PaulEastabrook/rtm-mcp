"""Tests for token bucket rate limiter and request statistics."""

import asyncio

import pytest

from rtm_mcp.rate_limiter import RateLimitStats, TokenBucket

# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_initial_tokens_filled(self) -> None:
        """Bucket starts pre-filled to capacity."""
        bucket = TokenBucket(capacity=3, refill_rate=0.9)
        assert bucket.tokens_available == pytest.approx(3.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_three_immediate_acquires(self) -> None:
        """First 3 acquires should succeed without waiting."""
        bucket = TokenBucket(capacity=3, refill_rate=0.9)
        for _ in range(3):
            await bucket.acquire()
        assert bucket.tokens_available == pytest.approx(0.0, abs=0.2)

    @pytest.mark.asyncio
    async def test_fourth_acquire_waits(self) -> None:
        """After 3 acquires, the 4th should block until refill."""
        bucket = TokenBucket(capacity=3, refill_rate=0.9)
        for _ in range(3):
            await bucket.acquire()

        # The 4th acquire should need to wait ~1.1s (1/0.9) for a token
        # Use a short timeout to verify it doesn't return immediately
        with pytest.raises(TimeoutError):
            await wait_for_with_timeout(bucket.acquire(), timeout=0.05)

    @pytest.mark.asyncio
    async def test_refill_over_time(self) -> None:
        """After draining, advancing time should yield new tokens."""
        bucket = TokenBucket(capacity=3, refill_rate=1.0)
        for _ in range(3):
            await bucket.acquire()

        # Simulate 2 seconds passing
        bucket._last_refill -= 2.0
        bucket._refill()
        assert bucket._tokens == pytest.approx(2.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_pause_drains_tokens(self) -> None:
        """pause() should drain tokens and set a future resume time."""
        bucket = TokenBucket(capacity=3, refill_rate=0.9)
        bucket.pause(2.0)
        assert bucket._tokens == 0.0
        assert bucket._paused_until > 0.0

    @pytest.mark.asyncio
    async def test_pause_delays_acquire(self) -> None:
        """After pause, acquire should wait for the pause to expire."""
        bucket = TokenBucket(capacity=3, refill_rate=0.9)
        bucket.pause(1.0)

        with pytest.raises(TimeoutError):
            await wait_for_with_timeout(bucket.acquire(), timeout=0.05)

    def test_capacity_respected(self) -> None:
        """Tokens never exceed capacity even after long idle."""
        bucket = TokenBucket(capacity=3, refill_rate=1.0)
        # Simulate 100 seconds of idle time
        bucket._last_refill -= 100.0
        bucket._refill()
        assert bucket._tokens == 3.0

    def test_tokens_available_property(self) -> None:
        """tokens_available should reflect approximate current state."""
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        bucket._tokens = 2.0
        # Simulate 1 second of refill
        bucket._last_refill -= 1.0
        assert bucket.tokens_available == pytest.approx(3.0, abs=0.1)


# ---------------------------------------------------------------------------
# RateLimitStats
# ---------------------------------------------------------------------------


class TestRateLimitStats:
    def test_empty_stats(self) -> None:
        """Fresh stats should all be zero."""
        stats = RateLimitStats()
        assert stats.requests_last_60s() == 0
        assert stats.retries_last_60s() == 0
        assert stats.http_503_count_session == 0

    def test_record_requests(self) -> None:
        stats = RateLimitStats()
        for _ in range(5):
            stats.record_request()
        assert stats.requests_last_60s() == 5

    def test_record_retries(self) -> None:
        stats = RateLimitStats()
        stats.record_retry()
        stats.record_retry()
        assert stats.retries_last_60s() == 2

    def test_503_session_counter(self) -> None:
        stats = RateLimitStats()
        stats.record_503()
        stats.record_503()
        stats.record_503()
        assert stats.http_503_count_session == 3

    def test_rolling_window_trims_old(self) -> None:
        """Entries older than 60s should be trimmed."""
        stats = RateLimitStats()
        # Add a request, then make it appear old
        stats.record_request()
        stats._request_timestamps[0] -= 120  # 120s ago
        # Add a fresh one
        stats.record_request()
        assert stats.requests_last_60s() == 1

    def test_request_type_accepted(self) -> None:
        """record_request should accept request_type without error."""
        stats = RateLimitStats()
        stats.record_request("read")
        stats.record_request("write")
        assert stats.requests_last_60s() == 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def wait_for_with_timeout(coro, timeout: float) -> None:
    """Raise TimeoutError if coro doesn't complete within timeout."""
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        raise TimeoutError from None
