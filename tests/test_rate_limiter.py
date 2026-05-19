"""
Tests for src/utils/rate_limiter.py — AdaptiveRateLimiter
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
import time

from src.utils.rate_limiter import AdaptiveRateLimiter


class TestAdaptiveRateLimiterInit:
    def test_default_params(self):
        rl = AdaptiveRateLimiter()
        assert rl.min_delay == 1.5
        assert rl.max_delay == 4.0
        assert rl.backoff_factor == 2.0
        assert rl._backoff_level == 0
        assert rl._current_delay == 1.5  # initialized to min_delay

    def test_custom_params(self):
        rl = AdaptiveRateLimiter(min_delay=0.5, max_delay=2.0, max_backoff=60.0)
        assert rl.min_delay == 0.5
        assert rl.max_delay == 2.0
        assert rl.max_backoff == 60.0


class TestOnSuccess:
    def test_on_success_decrements_backoff_level(self):
        rl = AdaptiveRateLimiter()
        rl._backoff_level = 3
        rl.on_success()
        assert rl._backoff_level == 2

    def test_on_success_at_zero_stays_zero(self):
        rl = AdaptiveRateLimiter()
        rl._backoff_level = 0
        rl.on_success()
        assert rl._backoff_level == 0

    def test_on_success_recalculates_delay(self):
        rl = AdaptiveRateLimiter(min_delay=1.0, max_delay=2.0)
        rl._backoff_level = 1
        rl.on_success()
        # After decrement to 0, delay should be in [min, max]
        assert rl.min_delay <= rl._current_delay <= rl.max_delay


class TestOnThrottle:
    def test_on_throttle_increments_level(self):
        rl = AdaptiveRateLimiter()
        rl.on_throttle()
        assert rl._backoff_level == 1

    def test_on_throttle_increases_delay(self):
        rl = AdaptiveRateLimiter(min_delay=1.0, max_delay=2.0, backoff_factor=2.0)
        initial_delay = rl._current_delay
        rl.on_throttle()
        assert rl._current_delay > initial_delay

    def test_on_throttle_multiple_times(self):
        rl = AdaptiveRateLimiter()
        rl.on_throttle()
        rl.on_throttle()
        assert rl._backoff_level == 2


class TestOnBan:
    def test_on_ban_increments_by_3(self):
        rl = AdaptiveRateLimiter()
        rl.on_ban()
        assert rl._backoff_level == 3

    def test_on_ban_delay_large(self):
        rl = AdaptiveRateLimiter(max_delay=4.0, backoff_factor=2.0)
        rl.on_ban()
        # At backoff level 3: base = max_delay * 2^3 = 32
        assert rl._current_delay > rl.max_delay


class TestRecalculateDelay:
    def test_level_zero_uses_random_in_range(self):
        rl = AdaptiveRateLimiter(min_delay=1.0, max_delay=2.0)
        rl._backoff_level = 0
        rl._recalculate_delay()
        assert rl.min_delay <= rl._current_delay <= rl.max_delay

    def test_level_nonzero_exponential(self):
        rl = AdaptiveRateLimiter(max_delay=4.0, backoff_factor=2.0)
        rl._backoff_level = 2
        rl._recalculate_delay()
        # base = 4.0 * 2^2 = 16.0, capped at max_backoff
        expected_base = 4.0 * (2.0 ** 2)
        assert rl._current_delay == min(expected_base, rl.max_backoff)

    def test_capped_at_max_backoff(self):
        rl = AdaptiveRateLimiter(max_delay=4.0, backoff_factor=2.0, max_backoff=10.0)
        rl._backoff_level = 10
        rl._recalculate_delay()
        assert rl._current_delay == 10.0


class TestWait:
    @pytest.mark.asyncio
    async def test_wait_records_request_time(self):
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=0.05)
        rl._current_delay = 0.01
        rl._last_request_time = 0.0
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await rl.wait()
        assert len(rl._request_times) == 1

    @pytest.mark.asyncio
    async def test_wait_skips_sleep_when_not_needed(self):
        rl = AdaptiveRateLimiter(min_delay=0.01, max_delay=0.05)
        rl._current_delay = 0.01
        # Set last_request_time to long ago so elapsed > wait_time
        rl._last_request_time = time.monotonic() - 100.0
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await rl.wait()
        mock_sleep.assert_not_called()


class TestRequestsPerMinute:
    def test_zero_requests(self):
        rl = AdaptiveRateLimiter()
        assert rl.requests_per_minute == 0

    def test_counts_recent_requests(self):
        rl = AdaptiveRateLimiter()
        now = time.monotonic()
        rl._request_times.append(now - 10)
        rl._request_times.append(now - 20)
        rl._request_times.append(now - 70)  # older than 60s, not counted
        assert rl.requests_per_minute == 2


class TestCurrentDelay:
    def test_current_delay_property(self):
        rl = AdaptiveRateLimiter(min_delay=1.0, max_delay=3.0)
        assert rl.current_delay == rl._current_delay


class TestLongPause:
    @pytest.mark.asyncio
    async def test_long_pause_default(self):
        rl = AdaptiveRateLimiter()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await rl.long_pause(seconds=10.0)
        assert mock_sleep.call_count == 2  # 10/5 = 2 chunks

    @pytest.mark.asyncio
    async def test_long_pause_exact_seconds(self):
        rl = AdaptiveRateLimiter()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await rl.long_pause(seconds=15.0)
        assert mock_sleep.call_count == 3  # 15/5 = 3 chunks

    @pytest.mark.asyncio
    async def test_long_pause_no_args_uses_random(self):
        rl = AdaptiveRateLimiter()
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch("random.uniform", return_value=30.0):
                await rl.long_pause()
        # 30/5 = 6 chunks
        assert mock_sleep.call_count == 6
