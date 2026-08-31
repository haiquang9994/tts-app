import asyncio
from pathlib import Path

import pytest
from edge_tts.exceptions import NoAudioReceived

from app import cache, tts
from app.config import Settings
from app.tts import Synthesizer, TTSError


@pytest.fixture(autouse=True)
def khong_cho_giua_cac_lan_retry(monkeypatch):
    monkeypatch.setattr(tts, "_RETRY_DELAYS", (0.0, 0.0, 0.0))


def make_settings(tmp_path: Path, **kw) -> Settings:
    return Settings(cache_dir=tmp_path, **kw)


async def test_get_audio_goi_provider_va_ghi_cache(tmp_path: Path):
    calls = []

    async def provider(text, voice, rate):
        calls.append((text, voice, rate))
        return b"MP3"

    s = Synthesizer(make_settings(tmp_path), provider=provider)
    key, data = await s.get_audio("xin chào", "vi-VN-HoaiMyNeural", "+20%")

    assert data == b"MP3"
    assert calls == [("xin chào", "vi-VN-HoaiMyNeural", "+20%")]
    assert cache.read(tmp_path, key) == b"MP3"


async def test_cache_hit_khong_goi_provider_lan_hai(tmp_path: Path):
    calls = []

    async def provider(text, voice, rate):
        calls.append(text)
        return b"MP3"

    s = Synthesizer(make_settings(tmp_path), provider=provider)
    await s.get_audio("xin chào", "vi-VN-HoaiMyNeural", "+20%")
    await s.get_audio("xin chào", "vi-VN-HoaiMyNeural", "+20%")

    assert len(calls) == 1


async def test_single_flight_hai_request_dong_thoi_chi_goi_provider_mot_lan(tmp_path: Path):
    calls = []
    thanh_cong = asyncio.Event()

    async def provider(text, voice, rate):
        calls.append(text)
        await thanh_cong.wait()
        return b"MP3"

    s = Synthesizer(make_settings(tmp_path), provider=provider)
    t1 = asyncio.create_task(s.get_audio("a", "vi-VN-HoaiMyNeural", "+20%"))
    t2 = asyncio.create_task(s.get_audio("a", "vi-VN-HoaiMyNeural", "+20%"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    thanh_cong.set()
    r1, r2 = await asyncio.gather(t1, t2)

    assert len(calls) == 1
    assert r1 == r2


async def test_retry_thanh_cong_o_lan_thu_ba(tmp_path: Path):
    lan = {"n": 0}

    async def provider(text, voice, rate):
        lan["n"] += 1
        if lan["n"] < 3:
            raise OSError("mạng chập chờn")
        return b"MP3"

    s = Synthesizer(make_settings(tmp_path), provider=provider)
    _, data = await s.get_audio("a", "vi-VN-HoaiMyNeural", "+20%")

    assert data == b"MP3"
    assert lan["n"] == 3


async def test_retry_kich_hoat_voi_loi_rieng_cua_edge_tts(tmp_path: Path):
    # EdgeTTSException kế thừa Exception chứ KHÔNG phải OSError. Nếu danh sách
    # bắt lỗi chỉ có OSError thì retry không bao giờ chạy cho đúng kiểu hỏng
    # phổ biến nhất, và lỗi lọt ra thành 500 thay vì 503.
    lan = {"n": 0}

    async def provider(text, voice, rate):
        lan["n"] += 1
        if lan["n"] < 2:
            raise NoAudioReceived("không nhận được audio")
        return b"MP3"

    s = Synthesizer(make_settings(tmp_path), provider=provider)
    _, data = await s.get_audio("a", "vi-VN-HoaiMyNeural", "+20%")

    assert data == b"MP3"
    assert lan["n"] == 2


async def test_het_luot_retry_thi_nem_ttserror(tmp_path: Path):
    async def provider(text, voice, rate):
        raise OSError("hỏng")

    s = Synthesizer(make_settings(tmp_path), provider=provider)
    with pytest.raises(TTSError):
        await s.get_audio("a", "vi-VN-HoaiMyNeural", "+20%")


async def test_that_bai_khong_de_lai_gi_trong_cache(tmp_path: Path):
    async def provider(text, voice, rate):
        raise OSError("hỏng")

    s = Synthesizer(make_settings(tmp_path), provider=provider)
    with pytest.raises(TTSError):
        await s.get_audio("a", "vi-VN-HoaiMyNeural", "+20%")

    assert list(tmp_path.glob("*.mp3")) == []
    assert list(tmp_path.glob("*.tmp")) == []


async def test_semaphore_gioi_han_so_lan_goi_dong_thoi(tmp_path: Path):
    dang_chay = 0
    cao_nhat = 0

    async def provider(text, voice, rate):
        nonlocal dang_chay, cao_nhat
        dang_chay += 1
        cao_nhat = max(cao_nhat, dang_chay)
        await asyncio.sleep(0.01)
        dang_chay -= 1
        return b"MP3"

    s = Synthesizer(make_settings(tmp_path, tts_max_concurrency=2), provider=provider)
    await asyncio.gather(*[
        s.get_audio(f"cau {i}", "vi-VN-HoaiMyNeural", "+20%") for i in range(8)
    ])

    assert cao_nhat <= 2


async def test_timeout_duoc_tinh_la_that_bai(tmp_path: Path):
    async def provider(text, voice, rate):
        await asyncio.sleep(5)
        return b"MP3"

    s = Synthesizer(make_settings(tmp_path, tts_timeout_seconds=0), provider=provider)
    with pytest.raises(TTSError):
        await s.get_audio("a", "vi-VN-HoaiMyNeural", "+20%")
