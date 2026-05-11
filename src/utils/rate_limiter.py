"""
Adaptive rate limiter với exponential backoff.
Tự động giảm tốc độ khi bị throttle, tăng lại khi ổn.
"""
import asyncio
import time
import random
from collections import deque
from loguru import logger


class AdaptiveRateLimiter:
    """
    Tự điều chỉnh delay dựa trên tình trạng scraping:
    - Bình thường: delay min-max giây
    - Khi bị throttle: exponential backoff
    - Sau khi backoff: dần dần phục hồi tốc độ
    """

    def __init__(
        self,
        min_delay: float = 1.5,
        max_delay: float = 4.0,
        max_backoff: float = 300.0,   # 5 phút tối đa
        backoff_factor: float = 2.0,
        jitter: float = 0.3,           # ±30% ngẫu nhiên
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_backoff = max_backoff
        self.backoff_factor = backoff_factor
        self.jitter = jitter

        self._current_delay = min_delay
        self._backoff_level = 0
        self._last_request_time = 0.0
        self._request_times: deque = deque(maxlen=100)  # rolling window

    async def wait(self):
        """Chờ đúng lượng thời gian cần thiết trước request tiếp theo"""
        now = time.monotonic()
        elapsed = now - self._last_request_time

        wait_time = self._current_delay
        # Thêm jitter để tránh pattern đều đặn
        jitter_amount = wait_time * self.jitter * random.uniform(-1, 1)
        wait_time = max(0.5, wait_time + jitter_amount)

        remaining = wait_time - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

        self._last_request_time = time.monotonic()
        self._request_times.append(self._last_request_time)

    def on_success(self):
        """Gọi sau mỗi request thành công — dần phục hồi tốc độ"""
        if self._backoff_level > 0:
            self._backoff_level -= 1
            self._recalculate_delay()
            logger.debug(f"Rate limiter recovering: delay={self._current_delay:.1f}s (level {self._backoff_level})")

    def on_throttle(self):
        """Gọi khi bị rate-limit — tăng delay theo exponential backoff"""
        self._backoff_level += 1
        self._recalculate_delay()
        logger.warning(f"Rate limit hit! Backing off: delay={self._current_delay:.1f}s (level {self._backoff_level})")

    def on_ban(self):
        """Gọi khi bị ban/checkpoint — backoff lớn"""
        self._backoff_level += 3
        self._recalculate_delay()
        logger.error(f"Ban detected! Long backoff: delay={self._current_delay:.1f}s (level {self._backoff_level})")

    def _recalculate_delay(self):
        if self._backoff_level == 0:
            self._current_delay = random.uniform(self.min_delay, self.max_delay)
        else:
            base = self.max_delay * (self.backoff_factor ** self._backoff_level)
            self._current_delay = min(base, self.max_backoff)

    async def long_pause(self, seconds: float = None):
        """Nghỉ dài — dùng khi bị ban hoặc cần cool down"""
        pause = seconds or random.uniform(30, 90)
        logger.info(f"Long pause: {pause:.0f}s...")
        # Nghỉ theo chunks để có thể cancel nếu cần
        chunks = int(pause / 5)
        for i in range(chunks):
            await asyncio.sleep(5)
            if (i + 1) % 6 == 0:  # mỗi 30s log tiến trình
                remaining = pause - (i + 1) * 5
                logger.debug(f"  Pause remaining: {remaining:.0f}s")

    @property
    def requests_per_minute(self) -> float:
        """Tốc độ request hiện tại (req/min) trong 60s qua"""
        now = time.monotonic()
        recent = [t for t in self._request_times if now - t < 60]
        return len(recent)

    @property
    def current_delay(self) -> float:
        return self._current_delay
