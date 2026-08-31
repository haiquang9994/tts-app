"""Gọi MyMemory thật.

Bị loại khỏi lần chạy mặc định (pytest.ini). Chạy trước mỗi lần deploy: đây là
endpoint miễn phí của bên thứ ba, và chỉ có gọi thật mới biết họ đã đổi giao
thức, đổi giới hạn độ dài hay đã chặn máy chủ.

Cố ý gửi rất ít: hạn mức tính theo NGÀY và dùng chung cho cả máy chủ.
"""
import pytest

from app.translate import make_fetcher, translate

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_translates_english_to_vietnamese():
    fetch = make_fetcher(email="", timeout=30)
    out = await translate("The file is ready to read.", fetch=fetch)

    assert out
    assert out != "The file is ready to read."
    # Có dấu tiếng Việt nghĩa là đã dịch thật chứ không phải trả về nguyên văn.
    assert any(ch in out for ch in "àáảãạăâđêôơư")


@pytest.mark.asyncio
async def test_keeps_code_like_tokens_in_english():
    """Đây là điểm chính của module. Không có lớp bọc thì máy dịch biến
    'single-flight' thành 'một chuyến bay' và 'POST' thành 'BÀI'."""
    fetch = make_fetcher(email="", timeout=30)
    out = await translate(
        "It collapses duplicates via single-flight, then calls POST /api/tts.",
        fetch=fetch,
    )

    assert "single-flight" in out
    assert "POST" in out
    assert "/api/tts" in out


def test_rejects_a_query_over_the_documented_limit():
    """Khoá giới hạn 500 ký tự: nếu MyMemory nới ra thì test này báo cho ta biết."""
    from app.translate import _mymemory, TranslateError

    with pytest.raises(TranslateError, match="(?i)length"):
        _mymemory("word " * 120, email="", timeout=30)
