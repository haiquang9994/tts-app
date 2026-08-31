"""Gọi Gemini thật.

Bị loại khỏi lần chạy mặc định (pytest.ini). Chạy trước mỗi lần deploy: chỉ có
gọi thật mới biết tên model còn tồn tại, key còn sống, và hình dạng phản hồi
chưa đổi. Bỏ qua nếu chưa cấu hình key.

Cố ý gửi rất ít: mỗi lần chạy tốn tiền thật.
"""
import os
import pathlib

import pytest

from app.config import Settings
from app.translate import Translator, gemini_translate

pytestmark = pytest.mark.integration


def _env(name: str) -> str:
    """Đọc từ môi trường, không có thì đọc .env — để chạy test không cần export."""
    value = os.environ.get(name)
    if value:
        return value
    env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return ""


@pytest.fixture
def settings(tmp_path):
    key = _env("GEMINI_API_KEY")
    if not key:
        pytest.skip("chưa cấu hình GEMINI_API_KEY")
    return Settings(
        cache_dir=tmp_path,
        gemini_api_key=key,
        gemini_model=_env("GEMINI_MODEL") or "gemini-flash-lite-latest",
    )


@pytest.mark.asyncio
async def test_translates_and_keeps_code_like_tokens(settings):
    """Đây là điểm chính. Máy dịch thống kê biến 'single-flight' thành 'một
    chuyến bay' và 'POST' thành 'BÀI'; với Gemini thì yêu cầu nằm trong prompt."""
    out = await Translator(settings).translate(
        "It collapses duplicates via single-flight, then calls `POST /api/tts`."
    )

    assert "single-flight" in out
    assert "POST /api/tts" in out
    assert any(ch in out for ch in "àáảãạăâđêôơư"), "phần văn xuôi phải được dịch"


@pytest.mark.asyncio
async def test_preserves_markdown_structure(settings):
    """Tiêu đề và gạch đầu dòng phải còn nguyên: kết quả trả thẳng vào ô nhập,
    và 'mỗi dòng là một lượt đọc' là mô hình của app."""
    out = await Translator(settings).translate(
        "## Architecture\n\n- The file is ready to read.\n- The cache is warm."
    )

    assert out.startswith("## ")
    assert out.count("\n- ") == 2


def test_an_unknown_model_fails_loudly(settings):
    """Tên model đổi theo thời gian; hỏng thì phải báo rõ chứ không im lặng."""
    from app.translate import TranslateError

    with pytest.raises(TranslateError, match="HTTP 404"):
        gemini_translate("Hello.", api_key=settings.gemini_api_key,
                         model="gemini-khong-ton-tai", timeout=30)


def test_the_error_message_never_contains_the_api_key(settings):
    """URL gọi Gemini nhúng key, mà thông báo lỗi đi thẳng vào log."""
    from app.translate import TranslateError

    try:
        gemini_translate("Hello.", api_key=settings.gemini_api_key,
                         model="gemini-khong-ton-tai", timeout=30)
    except TranslateError as exc:
        assert settings.gemini_api_key not in str(exc)
    else:  # pragma: no cover
        pytest.fail("đáng lẽ phải hỏng")
