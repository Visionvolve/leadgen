"""Adaptive rate limiter with exponential backoff for API calls."""

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


class AdaptiveRateLimiter:
    """Token-bucket rate limiter that self-adjusts on 429 errors."""

    def __init__(self, max_rpm=20):
        self.max_rpm = max_rpm
        self.current_rpm = max_rpm
        self.timestamps = deque()
        self.lock = threading.Lock()
        self.consecutive_429s = 0
        self.paused_until = 0
        self._backoff_history = deque(maxlen=60)  # Track 429s in last 60s

    def acquire(self):
        """Block until a request slot is available."""
        while True:
            with self.lock:
                now = time.time()

                # Check if globally paused
                if now < self.paused_until:
                    wait = self.paused_until - now
                    logger.warning("Rate limiter paused, waiting %.1fs", wait)
                    time.sleep(wait)
                    continue

                # Remove timestamps older than 60s
                while self.timestamps and self.timestamps[0] < now - 60:
                    self.timestamps.popleft()

                # Check if under limit
                if len(self.timestamps) < self.current_rpm:
                    self.timestamps.append(now)
                    return

                # Wait until oldest timestamp expires
                sleep_time = 60 - (now - self.timestamps[0]) + 0.1

            time.sleep(min(sleep_time, 5))  # Re-check every 5s max

    def report_429(self):
        """Called when a 429 response is received."""
        with self.lock:
            self.consecutive_429s += 1
            self._backoff_history.append(time.time())

            # Count 429s in last 60s
            now = time.time()
            recent = sum(1 for t in self._backoff_history if t > now - 60)

            if self.consecutive_429s >= 5:
                # Emergency pause
                self.paused_until = now + 30
                logger.warning(
                    "RATE LIMIT EMERGENCY: %d consecutive 429s, pausing ALL workers "
                    "for 30s. Reducing RPM from %d to %d",
                    self.consecutive_429s,
                    self.current_rpm,
                    max(5, self.current_rpm // 2),
                )
                self.current_rpm = max(5, self.current_rpm // 2)
                self.consecutive_429s = 0
            elif recent >= 3:
                # Reduce RPM
                new_rpm = max(5, int(self.current_rpm * 0.7))
                logger.warning(
                    "Rate limited %d times in last 60s, reducing RPM from %d to %d",
                    recent,
                    self.current_rpm,
                    new_rpm,
                )
                self.current_rpm = new_rpm

    def report_success(self):
        """Called on successful API response. Gradually restores RPM."""
        with self.lock:
            self.consecutive_429s = 0
            if self.current_rpm < self.max_rpm:
                # Slowly restore: +1 RPM per success, up to max
                self.current_rpm = min(self.max_rpm, self.current_rpm + 1)

    @property
    def stats(self):
        with self.lock:
            return {
                "current_rpm": self.current_rpm,
                "max_rpm": self.max_rpm,
                "active_requests_last_60s": len(self.timestamps),
                "consecutive_429s": self.consecutive_429s,
            }
