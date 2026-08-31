"""Dịch qua Gemini: cache, trần chi phí ngày, và cách báo lỗi.

Không có test nào chạm mạng: nhà cung cấp luôn được tiêm bản giả.
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.translate import DailyBudget, TranslateError, Translator


# --- Trần chi phí theo ngày ---

def test_budget_allows_up_to_the_cap():
    clock = [1_000_000.0]
    budget = DailyBudget(3, clock=lambda: clock[0])

    assert [budget.allow() for _ in range(4)] == [True, True, True, False]


def test_budget_resets_on_the_next_day():
    clock = [1_000_000.0]
    budget = DailyBudget(2, clock=lambda: clock[0])
    assert budget.allow() and budget.allow()
    assert not budget.allow()

    clock[0] += 86_400  # sang ngày mới
    assert budget.allow()


def test_budget_of_zero_blocks_everything():
    """Đặt 0 là cách tắt hẳn Gemini mà không cần bỏ API key."""
    assert DailyBudget(0).allow() is False


def test_budget_reports_what_is_left():
    budget = DailyBudget(5)
    budget.allow()
    assert budget.remaining() == 4


# --- Dịch ---

@pytest.fixture
def settings(tmp_path):
    return Settings(cache_dir=tmp_path, gemini_api_key="k", gemini_max_per_day=10)


@pytest.mark.asyncio
async def test_translates_through_gemini(settings):
    calls = []

    def gemini(text):
        calls.append(text)
        return "Bản dịch của Gemini."

    out = await Translator(settings, gemini=gemini).translate("Hello.")
    assert out == "Bản dịch của Gemini."
    assert calls == ["Hello."]


@pytest.mark.asyncio
async def test_reports_a_provider_failure(settings):
    """Không còn lớp dự phòng: hỏng thì báo lỗi để giao diện giữ nguyên bản gốc,
    còn hơn lặng lẽ trả về bản dịch kém mà người dùng tưởng là bản tốt."""
    def gemini(text):
        raise TranslateError("Gemini hỏng")

    with pytest.raises(TranslateError):
        await Translator(settings, gemini=gemini).translate("Hello.")


@pytest.mark.asyncio
async def test_wraps_an_unexpected_error(settings):
    """Lỗi mạng của urllib không nằm trong cây thừa kế gọn gàng nào."""
    def gemini(text):
        raise OSError("mạng hỏng")

    with pytest.raises(TranslateError):
        await Translator(settings, gemini=gemini).translate("Hello.")


@pytest.mark.asyncio
async def test_refuses_when_the_daily_budget_is_gone(tmp_path):
    """Trần ngày là lớp chặn CHI PHÍ, độc lập với việc ai đăng nhập được."""
    settings = Settings(cache_dir=tmp_path, gemini_api_key="k", gemini_max_per_day=0)

    def gemini(text):  # pragma: no cover - không được gọi
        raise AssertionError("hết ngân sách thì không được gọi Gemini")

    with pytest.raises(TranslateError, match="ngân sách"):
        await Translator(settings, gemini=gemini).translate("Hello.")


@pytest.mark.asyncio
async def test_refuses_when_no_key_is_configured(tmp_path):
    settings = Settings(cache_dir=tmp_path, gemini_api_key="")

    def gemini(text):  # pragma: no cover - không được gọi
        raise AssertionError("không có key thì không được gọi Gemini")

    with pytest.raises(TranslateError, match="GEMINI_API_KEY"):
        await Translator(settings, gemini=gemini).translate("Hello.")


@pytest.mark.asyncio
async def test_budget_is_not_spent_on_a_cache_hit(settings):
    calls = []

    def gemini(text):
        calls.append(text)
        return "Bản dịch của Gemini."

    translator = Translator(settings, gemini=gemini)
    assert await translator.translate("Hello.") == "Bản dịch của Gemini."
    assert await translator.translate("Hello.") == "Bản dịch của Gemini."

    assert len(calls) == 1, "lần thứ hai phải lấy từ cache"
    assert translator.budget.remaining() == 9, "cache hit không được tiêu ngân sách"


@pytest.mark.asyncio
async def test_a_failed_translation_is_not_cached(settings):
    """Cache bản hỏng thì lần sau vẫn hỏng mà không còn cơ hội gọi lại."""
    state = {"broken": True}

    def gemini(text):
        if state["broken"]:
            raise TranslateError("tạm hỏng")
        return "Bản dịch của Gemini."

    translator = Translator(settings, gemini=gemini)
    with pytest.raises(TranslateError):
        await translator.translate("Hello.")

    state["broken"] = False
    assert await translator.translate("Hello.") == "Bản dịch của Gemini."
