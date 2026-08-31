"""Rate limit theo IP, và lấy IP thật của client khi đứng sau Cloudflare Tunnel."""
from __future__ import annotations

import time
from dataclasses import dataclass

# Frontend prefetch trước 3 mục cùng lúc nên cần biên độ dồn cụm.
BURST = 20
# Xoá bucket không đụng tới sau ngần này giây, tránh dict phình vô hạn.
_IDLE_TTL = 600.0
_PRUNE_WHEN_LARGER_THAN = 1000


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """Token bucket trong bộ nhớ.

    Bộ đếm mất khi khởi động lại — chấp nhận được, mục tiêu là chặn lạm dụng
    chứ không phải tính cước.
    """

    def __init__(self, per_minute: int, burst: int = BURST, clock=time.monotonic) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str) -> tuple[bool, float]:
        """Trả (cho_phép, số_giây_nên_chờ_nếu_bị_chặn)."""
        now = self._clock()
        if len(self._buckets) > _PRUNE_WHEN_LARGER_THAN:
            self._prune(now)

        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._burst, updated=now)
            self._buckets[key] = bucket

        bucket.tokens = min(self._burst, bucket.tokens + (now - bucket.updated) * self._rate)
        bucket.updated = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True, 0.0
        if self._rate <= 0:
            return False, 60.0
        return False, (1.0 - bucket.tokens) / self._rate

    def _prune(self, now: float) -> None:
        for key in [k for k, b in self._buckets.items() if now - b.updated > _IDLE_TTL]:
            del self._buckets[key]


def client_ip(request) -> str:
    """IP thật của client.

    cloudflared chạy network_mode: host và kết nối tới 127.0.0.1, nên
    request.client.host là 127.0.0.1 với MỌI người dùng — rate limit theo
    giá trị đó là vô dụng. Header CF-Connecting-IP tin được vì port chỉ bind
    vào 127.0.0.1, không ai từ Internet gọi thẳng vào được.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
