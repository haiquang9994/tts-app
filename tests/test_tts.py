import asyncio
from pathlib import Path

import pytest
from edge_tts.exceptions import NoAudioReceived

from app import cache, tts
from app.breaker import CLOSED, OPEN, ProviderGuard
from app.config import Settings
from app.tts import EDGE_VARIANT, GTTS_VARIANT, Synthesizer, TTSError, tempo_from_rate


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(tts, "_RETRY_DELAYS", (0.0, 0.0, 0.0))


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def make(tmp_path: Path, primary=None, fallback=None, guard=None, **kw):
    settings = Settings(cache_dir=tmp_path, **kw)
    return Synthesizer(settings, primary=primary, fallback=fallback, guard=guard)


def works(calls, payload=b"MP3"):
    async def provider(text):
        calls.append(text)
        return payload
    return provider


def fails(exc=None):
    async def provider(text):
        raise exc or OSError("hỏng")
    return provider


class BlockedError(Exception):
    """Giả lập gTTSError: nó mang theo đối tượng response ở thuộc tính `rsp`."""

    def __init__(self, status):
        super().__init__(f"{status} từ Google")
        self.rsp = type("R", (), {"status_code": status})()


@pytest.mark.parametrize("rate,expected", [
    ("+0%", 1.0), ("+20%", 1.2), ("+50%", 1.5), ("+100%", 2.0), ("-50%", 0.5),
])
def test_converts_rate_to_tempo(rate, expected):
    assert tempo_from_rate(rate) == pytest.approx(expected)


async def test_uses_gtts_and_caches_result(tmp_path: Path):
    calls = []
    s = make(tmp_path, primary=works(calls), fallback=fails())
    key, data = await s.get_audio("xin chào")

    assert data == b"MP3"
    assert calls == ["xin chào"]
    assert cache.read(tmp_path, key) == b"MP3"


async def test_cache_hit_skips_provider(tmp_path: Path):
    calls = []
    s = make(tmp_path, primary=works(calls), fallback=fails())
    await s.get_audio("xin chào")
    await s.get_audio("xin chào")

    assert len(calls) == 1


async def test_falls_back_to_edge_tts_when_gtts_fails(tmp_path: Path):
    calls = []
    s = make(tmp_path, primary=fails(), fallback=works(calls, b"EDGE"))
    _, data = await s.get_audio("xin chào")

    assert data == b"EDGE"
    assert calls == ["xin chào"]


async def test_fallback_audio_never_shadows_the_default_voice(tmp_path: Path):
    """Audio dự phòng nằm dưới khoá riêng, nên khi gTTS hồi phục thì lần gọi
    after lấy lại đúng giọng mặc định chứ không dùng bản edge-tts đã cache."""
    s = make(tmp_path, primary=fails(), fallback=works([], b"EDGE"))
    await s.get_audio("xin chào")

    gtts_key = cache.cache_key("xin chào", GTTS_VARIANT, "+20%")
    edge_key = cache.cache_key("xin chào", EDGE_VARIANT, "+0%")
    assert cache.read(tmp_path, gtts_key) is None
    assert cache.read(tmp_path, edge_key) == b"EDGE"

    s2 = make(tmp_path, primary=works([], b"GTTS"), fallback=fails())
    _, data = await s2.get_audio("xin chào")
    assert data == b"GTTS"


async def test_fallback_audio_is_cached_so_outage_does_not_hammer_edge(tmp_path: Path):
    calls = []
    s = make(tmp_path, primary=fails(), fallback=works(calls, b"EDGE"))
    await s.get_audio("xin chào")
    await s.get_audio("xin chào")

    assert len(calls) == 1


async def test_raises_when_both_providers_fail(tmp_path: Path):
    s = make(tmp_path, primary=fails(), fallback=fails())
    with pytest.raises(TTSError):
        await s.get_audio("xin chào")

    assert list(tmp_path.glob("*.mp3")) == []
    assert list(tmp_path.glob("*.tmp")) == []


async def test_retries_then_succeeds(tmp_path: Path):
    attempts = {"n": 0}

    async def provider(text):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("mạng chập chờn")
        return b"MP3"

    s = make(tmp_path, primary=provider, fallback=fails())
    _, data = await s.get_audio("a")

    assert data == b"MP3"
    assert attempts["n"] == 3


async def test_retries_on_edge_tts_specific_errors(tmp_path: Path):
    # EdgeTTSException kế thừa Exception chứ KHÔNG phải OSError.
    attempts = {"n": 0}

    async def provider(text):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise NoAudioReceived("không nhận được audio")
        return b"EDGE"

    s = make(tmp_path, primary=fails(), fallback=provider)
    _, data = await s.get_audio("a")

    assert data == b"EDGE"
    assert attempts["n"] == 2


@pytest.mark.parametrize("status", [429, 403])
async def test_does_not_retry_after_being_blocked(tmp_path: Path, status):
    """Thử lại khi đã bị chặn chỉ làm bị chặn lâu hơn."""
    attempts = {"n": 0}

    async def provider(text):
        attempts["n"] += 1
        raise BlockedError(status)

    s = make(tmp_path, primary=provider, fallback=works([], b"EDGE"))
    _, data = await s.get_audio("a")

    assert attempts["n"] == 1
    assert data == b"EDGE"


@pytest.mark.parametrize("status", [429, 403])
async def test_blocked_response_opens_circuit_immediately(tmp_path: Path, status):
    guard = ProviderGuard(failure_threshold=99, clock=FakeClock())

    async def provider(text):
        raise BlockedError(status)

    s = make(tmp_path, primary=provider, fallback=works([], b"EDGE"), guard=guard)
    await s.get_audio("a")

    assert guard.state == OPEN


async def test_open_circuit_skips_gtts_entirely(tmp_path: Path):
    clock = FakeClock()
    guard = ProviderGuard(cooldown_seconds=300.0, clock=clock)
    gtts_calls = []
    edge_calls = []
    s = make(tmp_path, primary=works(gtts_calls), fallback=works(edge_calls, b"EDGE"), guard=guard)

    guard.record_failure("bị chặn", blocked=True)
    await s.get_audio("câu một")
    await s.get_audio("câu hai")

    assert gtts_calls == []
    assert len(edge_calls) == 2


async def test_exhausted_budget_uses_edge_without_touching_google(tmp_path: Path):
    guard = ProviderGuard(max_per_minute=2, clock=FakeClock())
    gtts_calls = []
    edge_calls = []
    s = make(tmp_path, primary=works(gtts_calls), fallback=works(edge_calls, b"EDGE"), guard=guard)

    for i in range(5):
        await s.get_audio(f"câu {i}")

    assert len(gtts_calls) == 2
    assert len(edge_calls) == 3
    # Hết ngân sách không phải là hỏng.
    assert guard.state == CLOSED


async def test_circuit_recovers_after_cooldown(tmp_path: Path):
    clock = FakeClock()
    guard = ProviderGuard(cooldown_seconds=60.0, clock=clock)
    gtts_calls = []
    s = make(tmp_path, primary=works(gtts_calls, b"GTTS"),
             fallback=works([], b"EDGE"), guard=guard)

    guard.record_failure("bị chặn", blocked=True)
    _, during = await s.get_audio("câu một")
    assert during == b"EDGE"

    clock.advance(61)
    _, after = await s.get_audio("câu hai")

    assert after == b"GTTS"
    assert guard.state == CLOSED


async def test_single_flight_collapses_concurrent_requests(tmp_path: Path):
    calls = []
    done = asyncio.Event()

    async def provider(text):
        calls.append(text)
        await done.wait()
        return b"MP3"

    s = make(tmp_path, primary=provider, fallback=fails())
    t1 = asyncio.create_task(s.get_audio("a"))
    t2 = asyncio.create_task(s.get_audio("a"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    done.set()
    r1, r2 = await asyncio.gather(t1, t2)

    assert len(calls) == 1
    assert r1 == r2


async def test_semaphore_caps_concurrent_calls(tmp_path: Path):
    running = 0
    peak = 0

    async def provider(text):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return b"MP3"

    s = make(tmp_path, primary=provider, fallback=fails(), tts_max_concurrency=2)
    await asyncio.gather(*[s.get_audio(f"câu {i}") for i in range(8)])

    assert peak <= 2


async def test_timeout_counts_as_failure(tmp_path: Path):
    async def provider(text):
        await asyncio.sleep(5)
        return b"MP3"

    s = make(tmp_path, primary=provider, fallback=provider, tts_timeout_seconds=0)
    with pytest.raises(TTSError):
        await s.get_audio("a")
