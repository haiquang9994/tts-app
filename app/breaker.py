"""Cầu dao cho gTTS: chặn trước khi Google chặn mình.

Hai cơ chế bổ trợ nhau:

* **Ngân sách chủ động** — token bucket giới hạn số lần gọi gTTS mỗi phút.
  Hết lượt thì đi thẳng sang nhà cung cấp dự phòng, không chạm tới Google.
  Đây là phần "ước lượng trước khi bị chặn".
* **Cầu dao phản ứng** — gặp lỗi thì mở, dồn toàn bộ lưu lượng sang dự phòng
  trong một khoảng nghỉ, rồi thử lại đúng một request để dò xem đã hồi phục
  chưa. Mỗi lần phải mở lại liên tiếp thì khoảng nghỉ nhân đôi.

Tín hiệu bị chặn rõ ràng (HTTP 429 hoặc 403) mở cầu dao ngay lập tức, không đợi
đủ số lần hỏng liên tiếp: cố thêm lúc đó chỉ làm Google chặn lâu hơn.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


@dataclass
class ProviderGuard:
    """Quyết định có được phép gọi nhà cung cấp chính hay không."""

    max_per_minute: int = 20
    failure_threshold: int = 3
    cooldown_seconds: float = 300.0
    max_cooldown_seconds: float = 3600.0
    clock: object = time.monotonic

    state: str = field(default=CLOSED, init=False)
    consecutive_failures: int = field(default=0, init=False)
    last_error: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.max_per_minute)
        self._tokens_updated = self.clock()
        self._opened_until = 0.0
        self._cooldown = self.cooldown_seconds
        self._probe_in_flight = False

    # ---- quyết định ----

    def allow(self) -> bool:
        now = self.clock()

        if self.state == OPEN:
            if now < self._opened_until:
                return False
            # Hết khoảng nghỉ: chuyển sang dò thử.
            self.state = HALF_OPEN
            self._probe_in_flight = False

        if self.state == HALF_OPEN:
            if self._probe_in_flight:
                return False
            # Đúng một request được thử, và không tiêu ngân sách.
            self._probe_in_flight = True
            return True

        return self._take_token(now)

    def _take_token(self, now: float) -> bool:
        rate = self.max_per_minute / 60.0
        self._tokens = min(
            float(self.max_per_minute), self._tokens + (now - self._tokens_updated) * rate
        )
        self._tokens_updated = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    # ---- phản hồi kết quả ----

    def record_success(self) -> None:
        self.state = CLOSED
        self.consecutive_failures = 0
        self.last_error = None
        self._cooldown = self.cooldown_seconds
        self._probe_in_flight = False

    def record_failure(self, error: str, blocked: bool = False) -> None:
        self.consecutive_failures += 1
        self.last_error = error
        was_probing = self.state == HALF_OPEN
        self._probe_in_flight = False

        if blocked or was_probing or self.consecutive_failures >= self.failure_threshold:
            self._open()

    def _open(self) -> None:
        self.state = OPEN
        self._opened_until = self.clock() + self._cooldown
        self._cooldown = min(self._cooldown * 2, self.max_cooldown_seconds)

    # ---- quan sát ----

    def status(self) -> dict:
        now = self.clock()
        rate = self.max_per_minute / 60.0
        tokens = min(
            float(self.max_per_minute), self._tokens + (now - self._tokens_updated) * rate
        )
        return {
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "seconds_until_retry": (
                round(max(0.0, self._opened_until - now), 1) if self.state == OPEN else 0.0
            ),
            "next_cooldown_seconds": self._cooldown,
            "budget_remaining": int(tokens),
            "budget_per_minute": self.max_per_minute,
            "last_error": self.last_error,
        }
