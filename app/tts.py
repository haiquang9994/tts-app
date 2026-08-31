"""Sinh audio từ văn bản.

Chuỗi nhà cung cấp:

  1. gTTS (Google) — mặc định. Tăng tốc bằng sox, hai cách chọn qua
     TTS_SPEED_MODE: `tempo` (WSOLA, giữ nguyên cao độ) hoặc `resample` (đổi
     sample rate, giọng cao lên theo tốc độ). Dùng sox chứ không dùng ffmpeg vì
     cùng thuật toán mà chỉ thêm ~12MB vào image, trong khi ffmpeg thêm tới
     ~450MB.
  2. edge-tts (Microsoft) — dùng khi gTTS hỏng hoặc khi cầu dao đang mở. Luôn
     giọng HoaiMy và KHÔNG đổi tốc độ.

Cache hai tầng: audio của mỗi nhà cung cấp nằm dưới khoá riêng. Tra khoá gTTS
trước, chỉ khi cầu dao mở mới tra tới khoá edge-tts. Nhờ vậy giọng dự phòng
không bao giờ lấn giọng mặc định, mà một đợt Google chặn kéo dài cũng không
khiến mỗi lần nghe lại đều phải gọi ra ngoài.

Module này không biết gì về HTTP.
"""
from __future__ import annotations

import asyncio
import functools
import io
import logging
import subprocess
from typing import Awaitable, Callable

import edge_tts
from gtts import gTTS

from . import cache
from .breaker import ProviderGuard
from .config import DEFAULT_SPEED_MODE, Settings
from .text import speak_paths

log = logging.getLogger(__name__)

# Độ trễ trước mỗi lần thử. Phần tử đầu là 0 vì lần đầu không chờ.
# Test monkeypatch giá trị này để khỏi phải chờ thật.
_RETRY_DELAYS: tuple[float, ...] = (0.0, 0.5, 1.5)

# Định danh biến thể audio dùng làm khoá cache. Đổi giá trị nếu cách sinh audio
# thay đổi, để cache cũ không bị dùng nhầm.
GTTS_VARIANT = "gtts-vi"
EDGE_VARIANT = "edge-vi"

# gTTS trả MP3 64kbps. Không ép bitrate thì cả sox lẫn ffmpeg đều mã hoá lại ở
# 32kbps mặc định, tức là bước tăng tốc âm thầm làm giảm một nửa chất lượng.
_MP3_BITRATE_KBPS = 64

# Chế độ tăng tốc -> hiệu ứng sox. `tempo` giãn thời gian nên cao độ không
# đổi; `speed` chỉ đọc mẫu ở nhịp khác rồi lấy mẫu lại, nên vừa nhanh hơn vừa
# cao hơn đúng bấy nhiêu lần.
_SOX_EFFECT = {"tempo": "tempo", "resample": "speed"}

# Mã HTTP cho thấy Google đã chặn chứ không phải trục trặc thoáng qua.
_BLOCKED_STATUS = (403, 429)

Provider = Callable[[str], Awaitable[bytes]]


class TTSError(RuntimeError):
    """Nhà cung cấp TTS không trả về được audio."""

    def __init__(self, message: str, blocked: bool = False) -> None:
        super().__init__(message)
        self.blocked = blocked


def is_blocked_error(exc: BaseException) -> bool:
    """gTTSError mang theo đối tượng response, đọc được mã trạng thái từ đó."""
    response = getattr(exc, "rsp", None)
    return getattr(response, "status_code", None) in _BLOCKED_STATUS


def tempo_from_rate(rate: str) -> float:
    """'+20%' -> 1.2. Khoảng -50%..+100% cho ra 0.5–2.0."""
    return 1.0 + int(rate.rstrip("%")) / 100.0


def speed_cache_key(rate: str, mode: str) -> str:
    """Phần khoá cache cho bước tăng tốc.

    Chế độ mặc định trả về đúng chuỗi rate như hồi chưa có TTS_SPEED_MODE, nên
    cache cũ vẫn dùng lại được; chỉ chế độ mới mới sinh khoá mới. Hai chế độ
    không bao giờ dùng chung file, vì cùng tốc độ mà khác hẳn cao độ.
    """
    if mode == DEFAULT_SPEED_MODE:
        return rate
    return f"{rate}|{mode}"


def _change_speed(data: bytes, rate: str, mode: str = DEFAULT_SPEED_MODE) -> bytes:
    tempo = tempo_from_rate(rate)
    if abs(tempo - 1.0) < 1e-9:
        return data
    proc = subprocess.run(
        ["sox", "-t", "mp3", "-",
         "-C", str(_MP3_BITRATE_KBPS), "-t", "mp3", "-",
         _SOX_EFFECT[mode], f"{tempo:g}"],
        input=data,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace")[:200]
        raise TTSError(f"sox đổi tốc độ hỏng: {detail}")
    return proc.stdout


def _gtts_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    gTTS(text, lang="vi", slow=False).write_to_fp(buffer)
    return buffer.getvalue()


async def gtts_provider(text: str, *, rate: str, mode: str = DEFAULT_SPEED_MODE) -> bytes:
    """gTTS là thư viện đồng bộ nên phải đẩy sang thread để không chặn vòng lặp."""
    # Chỉ gTTS mới cần bước này: nó đánh vần từng chữ cái khi gặp dấu chấm đứng
    # trước chữ. edge-tts đọc đường dẫn vốn đã ổn.
    data = await asyncio.to_thread(_gtts_bytes, speak_paths(text))
    if not data:
        raise TTSError("gTTS trả về dữ liệu rỗng")
    return await asyncio.to_thread(_change_speed, data, rate, mode)


async def edge_provider(text: str, *, voice: str, rate: str = "+0%") -> bytes:
    """Gọi edge-tts và gom toàn bộ chunk audio thành một khối MP3.

    Chạy hoàn toàn phía server: edge-tts mở WebSocket tới endpoint Azure Speech,
    không cần trình duyệt hay Chromium nào trong container.
    """
    chunks = bytearray()
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    if not chunks:
        raise TTSError("edge-tts trả về dữ liệu rỗng")
    return bytes(chunks)


class Synthesizer:
    def __init__(
        self,
        settings: Settings,
        primary: Provider | None = None,
        fallback: Provider | None = None,
        guard: ProviderGuard | None = None,
    ) -> None:
        self._settings = settings
        self._primary = primary or functools.partial(
            gtts_provider, rate=settings.tts_rate, mode=settings.tts_speed_mode
        )
        self._fallback = fallback or functools.partial(
            edge_provider, voice=settings.tts_fallback_voice, rate="+0%"
        )
        self._guard = guard or ProviderGuard(
            max_per_minute=settings.gtts_max_per_minute,
            failure_threshold=settings.gtts_failure_threshold,
            cooldown_seconds=settings.gtts_cooldown_seconds,
            max_cooldown_seconds=settings.gtts_max_cooldown_seconds,
        )
        self._semaphore = asyncio.Semaphore(settings.tts_max_concurrency)
        self._inflight: dict[str, asyncio.Future] = {}
        self._writes = 0

    @property
    def guard(self) -> ProviderGuard:
        return self._guard

    async def get_audio(self, final_text: str) -> tuple[str, bytes]:
        key = cache.cache_key(
            final_text,
            GTTS_VARIANT,
            speed_cache_key(self._settings.tts_rate, self._settings.tts_speed_mode),
        )

        data = cache.read(self._settings.cache_dir, key)
        if data is not None:
            return key, data

        existing = self._inflight.get(key)
        if existing is not None:
            # Single-flight: nhiều request cùng nội dung thì chỉ một cái gọi
            # thật ra ngoài, số còn lại chờ kết quả đó.
            return key, await asyncio.shield(existing)

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            data = await self._produce(final_text, key)
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # đánh dấu đã lấy, tránh cảnh báo lúc dọn rác
            raise
        else:
            future.set_result(data)
            return key, data
        finally:
            self._inflight.pop(key, None)

    async def _produce(self, text: str, key: str) -> bytes:
        if self._guard.allow():
            try:
                data = await self._call_with_retry(self._primary, text, "gTTS")
            except TTSError as exc:
                self._guard.record_failure(str(exc), blocked=exc.blocked)
                log.warning(
                    "gTTS hỏng (%s), chuyển sang edge-tts: %s",
                    "bị chặn" if exc.blocked else "lỗi thường", exc,
                )
            else:
                self._guard.record_success()
                await self._store(key, data)
                return data
        else:
            reason = "cầu dao đang mở" if self._guard.state != "closed" else "hết ngân sách"
            log.info("Bỏ qua gTTS (%s), dùng thẳng edge-tts", reason)

        return await self._fallback_audio(text)

    async def _fallback_audio(self, text: str) -> bytes:
        # Khoá riêng: giọng dự phòng không lấn giọng mặc định, mà một đợt chặn
        # kéo dài cũng không khiến mỗi lần nghe lại đều phải gọi ra ngoài.
        key = cache.cache_key(text, EDGE_VARIANT, "+0%")
        data = cache.read(self._settings.cache_dir, key)
        if data is not None:
            return data

        data = await self._call_with_retry(self._fallback, text, "edge-tts")
        await self._store(key, data)
        return data

    async def _store(self, key: str, data: bytes) -> None:
        cache.write(self._settings.cache_dir, key, data)
        self._writes += 1
        if self._writes % self._settings.cache_check_every == 0:
            # Quét cả thư mục, đẩy sang thread để không chặn vòng lặp sự kiện.
            await asyncio.to_thread(
                cache.enforce_limit,
                self._settings.cache_dir,
                self._settings.cache_max_mb,
            )

    async def _call_with_retry(self, provider: Provider, text: str, name: str) -> bytes:
        last: BaseException | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with self._semaphore:
                    return await asyncio.wait_for(
                        provider(text), timeout=self._settings.tts_timeout_seconds
                    )
            except Exception as exc:
                # Bắt rộng ở đúng ranh giới gọi ra ngoài. KHÔNG thu hẹp thành
                # OSError được: EdgeTTSException và aiohttp.ClientError đều kế
                # thừa thẳng Exception, nên danh sách hẹp làm retry không bao
                # giờ chạy cho đúng kiểu hỏng phổ biến nhất.
                # CancelledError kế thừa BaseException nên không bị nuốt ở đây.
                last = exc
                log.warning(
                    "%s hỏng lần %d/%d: %s: %s",
                    name, attempt + 1, len(_RETRY_DELAYS), type(exc).__name__, exc,
                )
                if is_blocked_error(exc) or getattr(exc, "blocked", False):
                    # Thử lại khi đã bị chặn chỉ làm bị chặn lâu hơn.
                    break

        blocked = is_blocked_error(last) or getattr(last, "blocked", False)
        raise TTSError(
            f"{name} thất bại: {type(last).__name__}: {last}", blocked=bool(blocked)
        )
