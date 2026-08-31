from app.breaker import CLOSED, HALF_OPEN, OPEN, ProviderGuard


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def make(**kw):
    clock = FakeClock()
    kw.setdefault("max_per_minute", 60)
    kw.setdefault("failure_threshold", 3)
    kw.setdefault("cooldown_seconds", 300.0)
    return ProviderGuard(clock=clock, **kw), clock


def test_allows_calls_while_healthy():
    guard, _ = make()
    assert all(guard.allow() for _ in range(10))
    assert guard.state == CLOSED


def test_budget_stops_calls_before_google_blocks_us():
    guard, _ = make(max_per_minute=3)
    assert [guard.allow() for _ in range(3)] == [True, True, True]
    assert guard.allow() is False
    # Hết ngân sách không phải là hỏng: cầu dao vẫn đóng.
    assert guard.state == CLOSED


def test_budget_refills_over_time():
    guard, clock = make(max_per_minute=60)
    for _ in range(60):
        guard.allow()
    assert guard.allow() is False
    clock.advance(1.0)
    assert guard.allow() is True


def test_opens_after_threshold_failures():
    guard, _ = make(failure_threshold=3)
    for _ in range(2):
        guard.record_failure("lỗi mạng")
    assert guard.state == CLOSED
    guard.record_failure("lỗi mạng")
    assert guard.state == OPEN
    assert guard.allow() is False


def test_blocked_response_opens_immediately():
    # 429/403 là tín hiệu chặn rõ ràng, cố thêm chỉ làm bị chặn lâu hơn.
    guard, _ = make(failure_threshold=99)
    guard.record_failure("429 Too Many Requests", blocked=True)
    assert guard.state == OPEN
    assert guard.allow() is False


def test_probes_once_after_cooldown():
    guard, clock = make(cooldown_seconds=300.0)
    guard.record_failure("chặn", blocked=True)
    clock.advance(299)
    assert guard.allow() is False

    clock.advance(2)
    assert guard.allow() is True          # request dò thử
    assert guard.state == HALF_OPEN
    assert guard.allow() is False         # chỉ đúng một request


def test_successful_probe_closes_circuit():
    guard, clock = make(cooldown_seconds=10.0)
    guard.record_failure("chặn", blocked=True)
    clock.advance(11)
    guard.allow()
    guard.record_success()

    assert guard.state == CLOSED
    assert guard.consecutive_failures == 0
    assert guard.last_error is None
    assert guard.allow() is True


def test_failed_probe_reopens_with_doubled_cooldown():
    guard, clock = make(cooldown_seconds=10.0)
    guard.record_failure("chặn", blocked=True)
    clock.advance(11)
    guard.allow()
    guard.record_failure("vẫn chặn")

    assert guard.state == OPEN
    clock.advance(11)
    assert guard.allow() is False         # khoảng nghỉ đã nhân đôi lên 20s
    clock.advance(10)
    assert guard.allow() is True


def test_cooldown_is_capped():
    guard, clock = make(cooldown_seconds=10.0, max_cooldown_seconds=40.0)
    for _ in range(10):
        guard.record_failure("chặn", blocked=True)
        clock.advance(10_000)
        guard.allow()
    assert guard.status()["next_cooldown_seconds"] == 40.0


def test_success_resets_cooldown_growth():
    guard, clock = make(cooldown_seconds=10.0)
    guard.record_failure("chặn", blocked=True)
    clock.advance(11)
    guard.allow()
    guard.record_failure("vẫn chặn")
    guard.record_success()
    assert guard.status()["next_cooldown_seconds"] == 10.0


def test_status_reports_everything_needed_to_diagnose():
    guard, clock = make(max_per_minute=10, cooldown_seconds=60.0)
    guard.allow()
    guard.record_failure("429 Too Many Requests", blocked=True)
    st = guard.status()

    assert st["state"] == OPEN
    assert st["consecutive_failures"] == 1
    assert st["last_error"] == "429 Too Many Requests"
    assert 59 <= st["seconds_until_retry"] <= 60
    assert st["budget_per_minute"] == 10
