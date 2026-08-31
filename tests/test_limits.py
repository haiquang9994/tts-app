from types import SimpleNamespace

from app.limits import RateLimiter, client_ip


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, giay):
        self.t += giay


def test_allows_up_to_burst_then_blocks():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=3, clock=clock)

    assert [rl.allow("ip")[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = rl.allow("ip")
    assert allowed is False
    assert retry_after > 0


def test_refills_tokens_over_time():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=1, clock=clock)

    assert rl.allow("ip")[0] is True
    assert rl.allow("ip")[0] is False
    clock.advance(1.0)  # 60/phút = 1 token mỗi giây
    assert rl.allow("ip")[0] is True


def test_counts_each_ip_separately():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=1, clock=clock)

    assert rl.allow("ip-a")[0] is True
    assert rl.allow("ip-b")[0] is True
    assert rl.allow("ip-a")[0] is False


def test_prunes_stale_buckets_to_bound_memory():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=1, clock=clock)
    for i in range(1100):
        rl.allow(f"ip-{i}")
    clock.advance(3600)
    rl.allow("ip-moi")

    assert len(rl._buckets) < 1100


def test_client_ip_prefers_cloudflare_header():
    req = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.7"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_takes_first_address_from_list():
    req = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.7, 198.51.100.2"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_socket_address():
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.5"))
    assert client_ip(req) == "10.0.0.5"


def test_client_ip_survives_missing_client():
    req = SimpleNamespace(headers={}, client=None)
    assert client_ip(req) == "unknown"
