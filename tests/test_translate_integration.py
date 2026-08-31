"""Gọi Gemini thật. TỐN TIỀN.

Mang marker `paid` chứ không phải `integration`, nên KHÔNG chạy cùng test tích
hợp của TTS: gTTS và edge-tts miễn phí nên chạy trước mỗi lần deploy là hợp lý,
còn ở đây mỗi lần chạy là tiền thật và ăn vào hạn mức request mỗi ngày.

    pytest                # 206 test offline, miễn phí
    pytest -m integration # TTS thật, miễn phí — chạy trước mỗi lần deploy
    pytest -m paid        # Gemini thật, TỐN TIỀN — chỉ khi cần kiểm chứng

Cả file cố ý gói gọn trong ĐÚNG HAI lời gọi: một lần dịch kiểm tra mọi tính
chất cùng lúc, một lần hỏng để kiểm tra đường báo lỗi. Gộp như vậy khó đọc hơn
tách nhỏ, nhưng tách nhỏ thì mỗi lần chạy đốt gấp đôi hạn mức.
"""
import os
import pathlib

import pytest

from app.config import Settings
from app.translate import Translator, gemini_translate

pytestmark = pytest.mark.paid


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
async def test_one_call_covers_every_property_we_depend_on(settings):
    """MỘT lời gọi, kiểm tra tất cả — mỗi lời gọi thêm là tiền thật.

    * định danh giữ nguyên tiếng Anh: máy dịch thống kê biến `single-flight`
      thành "một chuyến bay" và `POST` thành "BÀI"
    * cấu trúc Markdown còn nguyên: kết quả trả thẳng vào ô nhập, mà "mỗi dòng
      là một lượt đọc" là mô hình của app
    * phần văn xuôi thật sự được dịch
    """
    out = await Translator(settings).translate(
        "## Architecture\n\n"
        "- It collapses duplicates via single-flight, then calls `POST /api/tts`.\n"
        "- The file is ready to read."
    )

    assert "single-flight" in out
    assert "POST /api/tts" in out
    assert out.startswith("## ")
    assert out.count("\n- ") == 2
    assert any(ch in out for ch in "àáảãạăâđêôơư"), "phần văn xuôi phải được dịch"


def test_a_failure_is_loud_and_leaks_nothing(settings):
    """Một lời gọi hỏng, kiểm tra cả hai tính chất của đường báo lỗi.

    Tên model đổi theo thời gian nên hỏng phải báo rõ; và URL gọi Gemini nhúng
    API key ngay trong query string, mà thông báo lỗi thì đi thẳng vào log.
    """
    from app.translate import TranslateError

    with pytest.raises(TranslateError, match="HTTP 404") as caught:
        gemini_translate("Hello.", api_key=settings.gemini_api_key,
                         model="gemini-khong-ton-tai", timeout=30)

    assert settings.gemini_api_key not in str(caught.value)
