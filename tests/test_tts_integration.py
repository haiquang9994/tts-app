"""Test đánh thật ra mạng. Mặc định bị loại, chạy bằng: pytest -m integration

Test mock không bao giờ phát hiện được kiểu hỏng đáng lo nhất: Google hoặc
Microsoft đổi giao thức hay chặn server. Nên chạy bộ này trước mỗi lần deploy.
"""
import pytest

from app.tts import edge_provider, gtts_provider

pytestmark = pytest.mark.integration


def la_mp3(data: bytes) -> bool:
    # MP3 bắt đầu bằng tag ID3 hoặc frame sync 0xFF.
    return len(data) > 1000 and (data[:3] == b"ID3" or data[0] == 0xFF)


async def test_gtts_tra_ve_mp3_hop_le():
    data = await gtts_provider("Xin chào, đây là bài kiểm tra.", rate="+0%")
    assert la_mp3(data)


async def test_ffmpeg_tang_toc_lam_file_ngan_lai():
    goc = await gtts_provider("Xin chào, đây là một câu dài để đo thời lượng.", rate="+0%")
    nhanh = await gtts_provider("Xin chào, đây là một câu dài để đo thời lượng.", rate="+50%")

    assert la_mp3(nhanh)
    # Đọc nhanh hơn 1.5 lần thì file phải nhỏ đi rõ rệt.
    assert len(nhanh) < len(goc) * 0.85, f"gốc={len(goc)} nhanh={len(nhanh)}"


async def test_edge_tts_du_phong_van_dung_duoc():
    data = await edge_provider("Xin chào.", voice="vi-VN-HoaiMyNeural")
    assert la_mp3(data)
