from types import SimpleNamespace

from app.limits import RateLimiter, client_ip


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def tien(self, giay):
        self.t += giay


def test_cho_phep_toi_han_muc_burst_roi_chan():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=3, clock=clock)

    assert [rl.allow("ip")[0] for _ in range(3)] == [True, True, True]
    cho_phep, cho_bao_lau = rl.allow("ip")
    assert cho_phep is False
    assert cho_bao_lau > 0


def test_nap_lai_token_theo_thoi_gian():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=1, clock=clock)

    assert rl.allow("ip")[0] is True
    assert rl.allow("ip")[0] is False
    clock.tien(1.0)  # 60/phút = 1 token mỗi giây
    assert rl.allow("ip")[0] is True


def test_cac_ip_khac_nhau_dem_rieng():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=1, clock=clock)

    assert rl.allow("ip-a")[0] is True
    assert rl.allow("ip-b")[0] is True
    assert rl.allow("ip-a")[0] is False


def test_bucket_cu_bi_don_de_khong_phinh_bo_nho():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=1, clock=clock)
    for i in range(1100):
        rl.allow(f"ip-{i}")
    clock.tien(3600)
    rl.allow("ip-moi")

    assert len(rl._buckets) < 1100


def test_client_ip_uu_tien_header_cua_cloudflare():
    req = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.7"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_lay_dia_chi_dau_tien_khi_header_co_nhieu_gia_tri():
    req = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.7, 198.51.100.2"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert client_ip(req) == "203.0.113.7"


def test_client_ip_lui_ve_dia_chi_ket_noi_khi_khong_co_header():
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.5"))
    assert client_ip(req) == "10.0.0.5"


def test_client_ip_khong_vo_khi_khong_co_client():
    req = SimpleNamespace(headers={}, client=None)
    assert client_ip(req) == "unknown"
