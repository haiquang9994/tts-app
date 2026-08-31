"""Test đánh thật ra mạng. Mặc định bị loại, chạy bằng: pytest -m integration

Test mock không bao giờ phát hiện được kiểu hỏng đáng lo nhất: Google hoặc
Microsoft đổi giao thức hay chặn server. Nên chạy bộ này trước mỗi lần deploy.
"""
import shutil
import subprocess

import pytest

from app.tts import edge_provider, gtts_provider

pytestmark = pytest.mark.integration


def is_mp3(data: bytes) -> bool:
    # MP3 bắt đầu bằng tag ID3 hoặc frame sync 0xFF.
    return len(data) > 1000 and (data[:3] == b"ID3" or data[0] == 0xFF)


async def test_gtts_returns_valid_mp3():
    data = await gtts_provider("Xin chào, đây là bài kiểm tra.", rate="+0%")
    assert is_mp3(data)


@pytest.mark.skipif(shutil.which("sox") is None, reason="máy này chưa cài sox")
async def test_sox_speedup_shortens_the_file():
    goc = await gtts_provider("Xin chào, đây là một câu dài để đo thời lượng.", rate="+0%")
    nhanh = await gtts_provider("Xin chào, đây là một câu dài để đo thời lượng.", rate="+50%")

    assert is_mp3(nhanh)
    # Đọc nhanh 1.5 lần ở cùng bitrate thì file phải nhỏ đi tương ứng (~2/3).
    ty_le = len(nhanh) / len(goc)
    assert 0.55 < ty_le < 0.80, f"tỉ lệ {ty_le:.3f}: gốc={len(goc)} nhanh={len(nhanh)}"


@pytest.mark.skipif(shutil.which("sox") is None, reason="máy này chưa cài sox")
async def test_speedup_preserves_bitrate():
    """Không ép bitrate thì sox mã hoá lại ở 32kbps, mất một nửa chất lượng."""
    goc = await gtts_provider("Xin chào, đây là bài kiểm tra chất lượng.", rate="+0%")
    nhanh = await gtts_provider("Xin chào, đây là bài kiểm tra chất lượng.", rate="+20%")

    # Cùng bitrate thì kích thước tỉ lệ nghịch với tốc độ: 1/1.2 ~ 0.83.
    ty_le = len(nhanh) / len(goc)
    assert 0.75 < ty_le < 0.92, f"tỉ lệ {ty_le:.3f} — nhiều khả năng bitrate bị hạ"


async def test_edge_tts_fallback_still_works():
    data = await edge_provider("Xin chào.", voice="vi-VN-HoaiMyNeural")
    assert is_mp3(data)


def rough_frequency(data: bytes) -> int:
    """Ước lượng cao độ bằng `sox stat` — đủ để phân biệt hai chế độ tăng tốc."""
    proc = subprocess.run(
        ["sox", "-t", "mp3", "-", "-n", "stat"],
        input=data, capture_output=True, check=True,
    )
    for line in proc.stderr.decode().splitlines():
        if "frequency" in line.lower():
            return int(line.split(":")[1])
    raise AssertionError("sox stat không in ra tần số")


@pytest.mark.skipif(shutil.which("sox") is None, reason="máy này chưa cài sox")
async def test_resample_mode_raises_the_pitch():
    cau = "Xin chào, đây là một câu dài để đo cao độ."
    tempo = await gtts_provider(cau, rate="+50%", mode="tempo")
    resample = await gtts_provider(cau, rate="+50%", mode="resample")

    assert is_mp3(resample)
    # Cùng độ dài (cùng tốc độ, cùng bitrate) nhưng cao độ lên đúng tỉ lệ 1.5.
    assert abs(len(resample) - len(tempo)) / len(tempo) < 0.1
    ty_le = rough_frequency(resample) / rough_frequency(tempo)
    assert 1.3 < ty_le < 1.7, f"tỉ lệ cao độ {ty_le:.2f} — resample không đổi cao độ"
