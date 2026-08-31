"""Test đánh thật ra mạng. Mặc định bị loại, chạy bằng: pytest -m integration

Test mock không bao giờ phát hiện được kiểu hỏng đáng lo nhất: Google hoặc
Microsoft đổi giao thức hay chặn server. Nên chạy bộ này trước mỗi lần deploy.
"""
import shutil

import pytest

from app.tts import edge_provider, gtts_provider

pytestmark = pytest.mark.integration


def la_mp3(data: bytes) -> bool:
    # MP3 bắt đầu bằng tag ID3 hoặc frame sync 0xFF.
    return len(data) > 1000 and (data[:3] == b"ID3" or data[0] == 0xFF)


async def test_gtts_tra_ve_mp3_hop_le():
    data = await gtts_provider("Xin chào, đây là bài kiểm tra.", rate="+0%")
    assert la_mp3(data)


@pytest.mark.skipif(shutil.which("sox") is None, reason="máy này chưa cài sox")
async def test_sox_tang_toc_lam_file_ngan_lai():
    goc = await gtts_provider("Xin chào, đây là một câu dài để đo thời lượng.", rate="+0%")
    nhanh = await gtts_provider("Xin chào, đây là một câu dài để đo thời lượng.", rate="+50%")

    assert la_mp3(nhanh)
    # Đọc nhanh 1.5 lần ở cùng bitrate thì file phải nhỏ đi tương ứng (~2/3).
    ty_le = len(nhanh) / len(goc)
    assert 0.55 < ty_le < 0.80, f"tỉ lệ {ty_le:.3f}: gốc={len(goc)} nhanh={len(nhanh)}"


@pytest.mark.skipif(shutil.which("sox") is None, reason="máy này chưa cài sox")
async def test_tang_toc_khong_lam_giam_bitrate():
    """Không ép bitrate thì sox mã hoá lại ở 32kbps, mất một nửa chất lượng."""
    goc = await gtts_provider("Xin chào, đây là bài kiểm tra chất lượng.", rate="+0%")
    nhanh = await gtts_provider("Xin chào, đây là bài kiểm tra chất lượng.", rate="+20%")

    # Cùng bitrate thì kích thước tỉ lệ nghịch với tốc độ: 1/1.2 ~ 0.83.
    ty_le = len(nhanh) / len(goc)
    assert 0.75 < ty_le < 0.92, f"tỉ lệ {ty_le:.3f} — nhiều khả năng bitrate bị hạ"


async def test_edge_tts_du_phong_van_dung_duoc():
    data = await edge_provider("Xin chào.", voice="vi-VN-HoaiMyNeural")
    assert la_mp3(data)
