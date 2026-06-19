from dataclasses import dataclass
from threading import Lock


@dataclass
class HttpMetricsSnapshot:
    requests_total: int
    error_responses_total: int
    rate_limited_total: int
    latency_ms_sum: int
    latency_ms_count: int
    latency_ms_max: int

    @property
    def latency_ms_avg(self) -> float:
        if self.latency_ms_count == 0:
            return 0.0
        return round(self.latency_ms_sum / self.latency_ms_count, 3)

    def as_metrics(self) -> dict[str, int | float]:
        return {
            "http_requests_total": self.requests_total,
            "http_error_responses_total": self.error_responses_total,
            "http_rate_limited_total": self.rate_limited_total,
            "http_latency_ms_sum": self.latency_ms_sum,
            "http_latency_ms_count": self.latency_ms_count,
            "http_latency_ms_max": self.latency_ms_max,
            "http_latency_ms_avg": self.latency_ms_avg,
        }


class InMemoryHttpMetrics:
    """Small single-process HTTP metrics collector for the POC deployment."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests_total = 0
        self._error_responses_total = 0
        self._rate_limited_total = 0
        self._latency_ms_sum = 0
        self._latency_ms_count = 0
        self._latency_ms_max = 0

    def record(self, *, status_code: int, latency_ms: int) -> None:
        with self._lock:
            self._requests_total += 1
            if status_code >= 500:
                self._error_responses_total += 1
            if status_code == 429:
                self._rate_limited_total += 1
            self._latency_ms_sum += latency_ms
            self._latency_ms_count += 1
            self._latency_ms_max = max(self._latency_ms_max, latency_ms)

    def snapshot(self) -> HttpMetricsSnapshot:
        with self._lock:
            return HttpMetricsSnapshot(
                requests_total=self._requests_total,
                error_responses_total=self._error_responses_total,
                rate_limited_total=self._rate_limited_total,
                latency_ms_sum=self._latency_ms_sum,
                latency_ms_count=self._latency_ms_count,
                latency_ms_max=self._latency_ms_max,
            )

    def clear(self) -> None:
        with self._lock:
            self._requests_total = 0
            self._error_responses_total = 0
            self._rate_limited_total = 0
            self._latency_ms_sum = 0
            self._latency_ms_count = 0
            self._latency_ms_max = 0
