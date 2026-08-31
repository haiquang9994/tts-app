"""Gọi MyMemory thật.

Bị loại khỏi lần chạy mặc định (pytest.ini). Chạy trước mỗi lần deploy: đây là
endpoint miễn phí của bên thứ ba, và chỉ có gọi thật mới biết họ đã đổi giao
thức, đổi giới hạn độ dài hay đã chặn máy chủ.

Cố ý gửi rất ít: hạn mức tính theo NGÀY và dùng chung cho cả máy chủ.
"""
import os
import pathlib

import pytest

from app.translate import make_fetcher, translate

pytestmark = pytest.mark.integration


def _email() -> str:
    """Email nâng hạn mức, lấy từ môi trường hoặc từ .env.

    Không có nó thì hạn mức ẩn danh chỉ 5.000 ký tự/ngày và chạy test vài lần
    là hết, khiến test đỏ vì hạn mức chứ không phải vì code hỏng.
    """
    from_env = os.environ.get("TRANSLATE_EMAIL")
    if from_env:
        return from_env
    env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TRANSLATE_EMAIL="):
                return line.split("=", 1)[1].strip()
    return ""


@pytest.mark.asyncio
async def test_translates_english_to_vietnamese():
    fetch = make_fetcher(email=_email(), timeout=30)
    out = await translate("The file is ready to read.", fetch=fetch)

    assert out
    assert out != "The file is ready to read."
    # Có dấu tiếng Việt nghĩa là đã dịch thật chứ không phải trả về nguyên văn.
    assert any(ch in out for ch in "àáảãạăâđêôơư")


@pytest.mark.asyncio
async def test_keeps_code_like_tokens_in_english():
    """Đây là điểm chính của module. Không có lớp bọc thì máy dịch biến
    'single-flight' thành 'một chuyến bay' và 'POST' thành 'BÀI'."""
    fetch = make_fetcher(email=_email(), timeout=30)
    out = await translate(
        "It collapses duplicates via single-flight, then calls POST /api/tts.",
        fetch=fetch,
    )

    assert "single-flight" in out
    assert "POST" in out
    assert "/api/tts" in out


def test_a_full_size_chunk_is_not_silently_truncated():
    """Đoạn dài đúng bằng MAX_QUERY_CHARS phải được dịch trọn vẹn.

    ĐO ĐƯỢC: giới hạn 500 ký tự chỉ áp dụng cho dùng ẩn danh — có email thì
    tới 1.500 ký tự vẫn trọn vẹn, nhưng ở 2.000 ký tự MyMemory CẮT BỚT mà
    KHÔNG báo lỗi (2.000 vào, 1.457 ra). Cắt âm thầm là kiểu hỏng tệ nhất, nên
    MAX_QUERY_CHARS giữ ở 470 cho an toàn với cả hai kiểu dùng. Test này canh
    đúng chỗ đó: nếu ngưỡng cắt tụt xuống dưới 470 thì nó đỏ.
    """
    from app.translate import MAX_QUERY_CHARS, _mymemory

    base = ("The breaker stops calling the provider before it blocks us. "
            "A per-minute budget skips the primary path when exhausted. ")
    chunk = (base * 8)[:MAX_QUERY_CHARS]
    out = _mymemory(chunk, email=_email(), timeout=30)

    assert len(out) > len(chunk) * 0.8, f"nghi bị cắt bớt: {len(chunk)} vào, {len(out)} ra"


@pytest.mark.asyncio
async def test_a_heading_still_gets_translated():
    """Khoá đặc tính đo được: chuỗi bắt đầu bằng '##' thì MyMemory trả về
    nguyên văn, không dịch. `_LEADING_MARKUP` tách dấu ra trước khi gửi.

    Nếu test này đỏ, hoặc MyMemory đã đổi hành vi, hoặc phần tách dấu đã hỏng.
    """
    fetch = make_fetcher(email=_email(), timeout=30)
    # Phải DÀI hơn ~100 ký tự: đoạn ngắn có "##" thì MyMemory vẫn dịch bình
    # thường, nên tiêu đề ngắn không tái hiện được lỗi.
    heading = ("## Architecture The request flow starts with a rate limit, then a "
               "length check, and finally the synthesizer returns the audio.")
    assert len(heading) > 100
    out = await translate(heading, fetch=fetch)

    assert out.startswith("## ")
    assert any(ch in out for ch in "àáảãạăâđêôơư"), "phần sau dấu ## phải được dịch"
