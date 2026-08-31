import asyncio
from pathlib import Path

import pytest
from edge_tts.exceptions import NoAudioReceived

from app import cache, tts
from app.config import Settings
from app.tts import Synthesizer, TTSError, tempo_tu_rate


@pytest.fixture(autouse=True)
def khong_cho_giua_cac_lan_retry(monkeypatch):
    monkeypatch.setattr(tts, "_RETRY_DELAYS", (0.0, 0.0, 0.0))


def make(tmp_path: Path, primary=None, fallback=None, **kw):
    settings = Settings(cache_dir=tmp_path, **kw)
    return Synthesizer(settings, primary=primary, fallback=fallback)


def provider_ok(nhan, tra=b"MP3"):
    async def p(text):
        nhan.append(text)
        return tra
    return p


def provider_hong(exc=OSError("hỏng")):
    async def p(text):
        raise exc
    return p


@pytest.mark.parametrize("rate,mong_doi", [
    ("+0%", 1.0), ("+20%", 1.2), ("+50%", 1.5), ("+100%", 2.0), ("-50%", 0.5),
])
def test_doi_rate_sang_tempo(rate, mong_doi):
    assert tempo_tu_rate(rate) == pytest.approx(mong_doi)


async def test_dung_gtts_va_ghi_cache(tmp_path: Path):
    goi = []
    s = make(tmp_path, primary=provider_ok(goi), fallback=provider_hong())
    key, data = await s.get_audio("xin chào")

    assert data == b"MP3"
    assert goi == ["xin chào"]
    assert cache.read(tmp_path, key) == b"MP3"


async def test_cache_hit_khong_goi_lai(tmp_path: Path):
    goi = []
    s = make(tmp_path, primary=provider_ok(goi), fallback=provider_hong())
    await s.get_audio("xin chào")
    await s.get_audio("xin chào")

    assert len(goi) == 1


async def test_gtts_hong_thi_roi_sang_edge_tts(tmp_path: Path):
    goi = []
    s = make(tmp_path, primary=provider_hong(), fallback=provider_ok(goi, b"EDGE"))
    _, data = await s.get_audio("xin chào")

    assert data == b"EDGE"
    assert goi == ["xin chào"]


async def test_khong_cache_ket_qua_du_phong(tmp_path: Path):
    # gTTS là giọng được chọn có chủ đích. Cache lại giọng edge-tts sẽ khiến
    # câu đó vĩnh viễn đọc bằng giọng không mong muốn.
    goi = []
    s = make(tmp_path, primary=provider_hong(), fallback=provider_ok(goi, b"EDGE"))
    key, _ = await s.get_audio("xin chào")

    assert cache.read(tmp_path, key) is None
    assert list(tmp_path.glob("*.mp3")) == []


async def test_gtts_hoi_phuc_thi_lay_lai_giong_gtts(tmp_path: Path):
    goi_edge = []
    s = make(tmp_path, primary=provider_hong(), fallback=provider_ok(goi_edge, b"EDGE"))
    _, d1 = await s.get_audio("xin chào")
    assert d1 == b"EDGE"

    goi_gtts = []
    s2 = make(tmp_path, primary=provider_ok(goi_gtts, b"GTTS"), fallback=provider_hong())
    key, d2 = await s2.get_audio("xin chào")

    assert d2 == b"GTTS"
    assert cache.read(tmp_path, key) == b"GTTS"


async def test_ca_hai_hong_thi_nem_ttserror(tmp_path: Path):
    s = make(tmp_path, primary=provider_hong(), fallback=provider_hong())
    with pytest.raises(TTSError):
        await s.get_audio("xin chào")

    assert list(tmp_path.glob("*.mp3")) == []
    assert list(tmp_path.glob("*.tmp")) == []


async def test_retry_thanh_cong_o_lan_thu_ba(tmp_path: Path):
    lan = {"n": 0}

    async def p(text):
        lan["n"] += 1
        if lan["n"] < 3:
            raise OSError("mạng chập chờn")
        return b"MP3"

    s = make(tmp_path, primary=p, fallback=provider_hong())
    _, data = await s.get_audio("a")

    assert data == b"MP3"
    assert lan["n"] == 3


async def test_retry_kich_hoat_voi_loi_rieng_cua_edge_tts(tmp_path: Path):
    # EdgeTTSException kế thừa Exception chứ KHÔNG phải OSError.
    lan = {"n": 0}

    async def p(text):
        lan["n"] += 1
        if lan["n"] < 2:
            raise NoAudioReceived("không nhận được audio")
        return b"EDGE"

    s = make(tmp_path, primary=provider_hong(), fallback=p)
    _, data = await s.get_audio("a")

    assert data == b"EDGE"
    assert lan["n"] == 2


async def test_single_flight_hai_request_dong_thoi_chi_goi_mot_lan(tmp_path: Path):
    goi = []
    xong = asyncio.Event()

    async def p(text):
        goi.append(text)
        await xong.wait()
        return b"MP3"

    s = make(tmp_path, primary=p, fallback=provider_hong())
    t1 = asyncio.create_task(s.get_audio("a"))
    t2 = asyncio.create_task(s.get_audio("a"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    xong.set()
    r1, r2 = await asyncio.gather(t1, t2)

    assert len(goi) == 1
    assert r1 == r2


async def test_semaphore_gioi_han_so_lan_goi_dong_thoi(tmp_path: Path):
    dang_chay = 0
    cao_nhat = 0

    async def p(text):
        nonlocal dang_chay, cao_nhat
        dang_chay += 1
        cao_nhat = max(cao_nhat, dang_chay)
        await asyncio.sleep(0.01)
        dang_chay -= 1
        return b"MP3"

    s = make(tmp_path, primary=p, fallback=provider_hong(), tts_max_concurrency=2)
    await asyncio.gather(*[s.get_audio(f"cau {i}") for i in range(8)])

    assert cao_nhat <= 2


async def test_timeout_duoc_tinh_la_that_bai(tmp_path: Path):
    async def p(text):
        await asyncio.sleep(5)
        return b"MP3"

    s = make(tmp_path, primary=p, fallback=p, tts_timeout_seconds=0)
    with pytest.raises(TTSError):
        await s.get_audio("a")
