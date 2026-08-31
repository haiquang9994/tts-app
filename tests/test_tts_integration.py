import pytest

from app.tts import edge_provider

pytestmark = pytest.mark.integration


async def test_edge_tts_tra_ve_mp3_hop_le():
    data = await edge_provider("Xin chào, đây là bài kiểm tra.", "vi-VN-HoaiMyNeural", "+20%")

    assert len(data) > 1000
    # MP3 bắt đầu bằng tag ID3 hoặc frame sync 0xFF 0xFB/0xF3/0xF2.
    assert data[:3] == b"ID3" or data[0] == 0xFF


async def test_ca_hai_giong_tieng_viet_deu_dung_duoc():
    for voice in ("vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"):
        data = await edge_provider("Xin chào.", voice, "+0%")
        assert len(data) > 1000
