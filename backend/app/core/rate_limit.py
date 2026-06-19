import math
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int = 0


class InMemoryRateLimiter:
    """Small fixed-window limiter for single-process POC deployments."""

    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str, limit: int, now: float | None = None) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=True, remaining=0)

        current_time = now if now is not None else time.time()
        cutoff = current_time - self.window_seconds

        with self._lock:
            requests = self._requests.setdefault(key, deque())
            while requests and requests[0] <= cutoff:
                requests.popleft()

            if len(requests) >= limit:
                retry_after = max(
                    1,
                    math.ceil(requests[0] + self.window_seconds - current_time),
                )
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=retry_after,
                )

            requests.append(current_time)
            return RateLimitResult(allowed=True, remaining=max(0, limit - len(requests)))

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()
