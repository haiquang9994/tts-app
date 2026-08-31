"""Chuỗi nhà cung cấp dịch: Gemini trước, MyMemory dự phòng.

Không có test nào chạm mạng: cả hai nhà cung cấp đều được tiêm bản giả.
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


# --- Chuỗi nhà cung cấp ---

@pytest.fixture
def settings(tmp_path):
    return Settings(cache_dir=tmp_path, gemini_api_key="k", gemini_max_per_day=10)


@pytest.mark.asyncio
async def test_uses_gemini_when_a_key_is_configured(settings):
    calls = []

    def gemini(text):
        calls.append(text)
        return "Bản dịch của Gemini."

    def mymemory(chunk):  # pragma: no cover - không được gọi
        raise AssertionError("không được chạm tới MyMemory khi Gemini chạy được")

    out = await Translator(settings, gemini=gemini, mymemory=mymemory).translate("Hello.")
    assert out == "Bản dịch của Gemini."
    assert calls == ["Hello."]


@pytest.mark.asyncio
async def test_falls_back_to_mymemory_when_gemini_fails(settings):
    def gemini(text):
        raise TranslateError("Gemini hỏng")

    def mymemory(chunk):
        return "Bản dịch dự phòng."

    out = await Translator(settings, gemini=gemini, mymemory=mymemory).translate("Hello.")
    assert out == "Bản dịch dự phòng."


@pytest.mark.asyncio
async def test_skips_gemini_when_the_daily_budget_is_gone(tmp_path):
    """Trần ngày là lớp chặn CHI PHÍ, độc lập với việc ai đăng nhập được."""
    settings = Settings(cache_dir=tmp_path, gemini_api_key="k", gemini_max_per_day=0)
    touched = []

    def gemini(text):  # pragma: no cover - không được gọi
        raise AssertionError("hết ngân sách thì không được gọi Gemini")

    def mymemory(chunk):
        touched.append(chunk)
        return "Bản dịch dự phòng."

    out = await Translator(settings, gemini=gemini, mymemory=mymemory).translate("Hello.")
    assert out == "Bản dịch dự phòng."
    assert touched


@pytest.mark.asyncio
async def test_skips_gemini_when_no_key_is_configured(tmp_path):
    settings = Settings(cache_dir=tmp_path, gemini_api_key="")

    def gemini(text):  # pragma: no cover - không được gọi
        raise AssertionError("không có key thì không được gọi Gemini")

    out = await Translator(
        settings, gemini=gemini, mymemory=lambda c: "Bản dịch dự phòng."
    ).translate("Hello.")
    assert out == "Bản dịch dự phòng."


@pytest.mark.asyncio
async def test_budget_is_not_spent_on_a_cache_hit(settings):
    calls = []

    def gemini(text):
        calls.append(text)
        return "Bản dịch của Gemini."

    translator = Translator(settings, gemini=gemini, mymemory=lambda c: "khong dung")
    assert await translator.translate("Hello.") == "Bản dịch của Gemini."
    assert await translator.translate("Hello.") == "Bản dịch của Gemini."

    assert len(calls) == 1, "lần thứ hai phải lấy từ cache"
    assert translator.budget.remaining() == 9, "cache hit không được tiêu ngân sách"


@pytest.mark.asyncio
async def test_each_provider_caches_under_its_own_key(settings):
    """Bản dịch dự phòng không được lấn bản dịch tốt, y như audio gTTS/edge-tts."""
    state = {"broken": True}

    def gemini(text):
        if state["broken"]:
            raise TranslateError("tạm hỏng")
        return "Bản dịch của Gemini."

    translator = Translator(settings, gemini=gemini, mymemory=lambda c: "Bản dịch dự phòng.")
    assert await translator.translate("Hello.") == "Bản dịch dự phòng."

    state["broken"] = False
    assert await translator.translate("Hello.") == "Bản dịch của Gemini."


@pytest.mark.asyncio
async def test_raises_when_both_providers_fail(settings):
    def broken(_):
        raise TranslateError("hỏng")

    with pytest.raises(TranslateError):
        await Translator(settings, gemini=broken, mymemory=broken).translate("Hello.")
