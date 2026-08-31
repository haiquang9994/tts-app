"""Sinh audio từ văn bản.

Chuỗi nhà cung cấp cố định:

  1. gTTS (Google) — mặc định, tăng tốc bằng bộ lọc `atempo` của ffmpeg nên
     giữ nguyên cao độ, không chói như hack đổi frame_rate của bản Django cũ.
  2. edge-tts (Microsoft) — chỉ dùng khi gTTS hỏng hẳn. Luôn giọng HoaiMy và
     KHÔNG đổi tốc độ.

Kết quả từ nhà cung cấp dự phòng **không được ghi vào cache**: gTTS là giọng
được chọn có chủ đích, cache lại giọng edge-tts sẽ khiến những câu rơi đúng vào
lúc Google chập chờn vĩnh viễn đọc bằng giọng không mong muốn.

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
from .config import Settings

log = logging.getLogger(__name__)

# Độ trễ trước mỗi lần thử. Phần tử đầu là 0 vì lần đầu không chờ.
# Test monkeypatch giá trị này để khỏi phải chờ thật.
_RETRY_DELAYS: tuple[float, ...] = (0.0, 0.5, 1.5)

# Định danh biến thể audio dùng làm khoá cache. Đổi giá trị này nếu cách sinh
# audio thay đổi để cache cũ không bị dùng nhầm.
_CACHE_VARIANT = "gtts-vi"

Provider = Callable[[str], Awaitable[bytes]]


class TTSError(RuntimeError):
    """Nhà cung cấp TTS không trả về được audio."""


def atempo_tu_rate(rate: str) -> float:
    """'+20%' -> 1.2. Bộ lọc atempo chỉ nhận 0.5–2.0, khớp đúng khoảng -50%..+100%."""
    return 1.0 + int(rate.rstrip("%")) / 100.0


def _doi_toc_do(data: bytes, rate: str) -> bytes:
    tempo = atempo_tu_rate(rate)
    if abs(tempo - 1.0) < 1e-9:
        return data
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-filter:a", f"atempo={tempo:g}", "-f", "mp3", "pipe:1"],
        input=data,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        loi = proc.stderr.decode("utf-8", "replace")[:200]
        raise TTSError(f"ffmpeg đổi tốc độ hỏng: {loi}")
    return proc.stdout


def _gtts_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    gTTS(text, lang="vi", slow=False).write_to_fp(buf)
    return buf.getvalue()


async def gtts_provider(text: str, *, rate: str) -> bytes:
    """gTTS là thư viện đồng bộ nên phải đẩy sang thread để không chặn vòng lặp."""
    data = await asyncio.to_thread(_gtts_bytes, text)
    if not data:
        raise TTSError("gTTS trả về dữ liệu rỗng")
    return await asyncio.to_thread(_doi_toc_do, data, rate)


async def edge_provider(text: str, *, voice: str, rate: str = "+0%") -> bytes:
    """Gọi edge-tts và gom toàn bộ chunk audio thành một khối MP3.

    Chạy hoàn toàn phía server: edge-tts mở WebSocket tới endpoint Azure
    Speech, không cần trình duyệt hay Chromium nào trong container.
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
    ) -> None:
        self._settings = settings
        self._primary = primary or functools.partial(gtts_provider, rate=settings.tts_rate)
        self._fallback = fallback or functools.partial(
            edge_provider, voice=settings.tts_fallback_voice, rate="+0%"
        )
        self._sem = asyncio.Semaphore(settings.tts_max_concurrency)
        self._inflight: dict[str, asyncio.Future] = {}
        self._writes = 0

    async def get_audio(self, final_text: str) -> tuple[str, bytes]:
        key = cache.cache_key(final_text, _CACHE_VARIANT, self._settings.tts_rate)

        data = cache.read(self._settings.cache_dir, key)
        if data is not None:
            return key, data

        existing = self._inflight.get(key)
        if existing is not None:
            # Single-flight: nhiều request cùng nội dung thì chỉ một cái gọi
            # thật ra ngoài, số còn lại chờ kết quả đó.
            return key, await asyncio.shield(existing)

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            data = await self._produce(final_text, key)
        except BaseException as exc:
            fut.set_exception(exc)
            fut.exception()  # đánh dấu đã lấy, tránh cảnh báo lúc dọn rác
            raise
        else:
            fut.set_result(data)
            return key, data
        finally:
            self._inflight.pop(key, None)

    async def _produce(self, text: str, key: str) -> bytes:
        try:
            data = await self._thu_lai(self._primary, text, "gTTS")
        except TTSError as exc:
            log.warning("gTTS hỏng hẳn, chuyển sang edge-tts: %s", exc)
            # Cố ý KHÔNG cache: xem docstring đầu module.
            return await self._thu_lai(self._fallback, text, "edge-tts")

        cache.write(self._settings.cache_dir, key, data)
        self._writes += 1
        if self._writes % self._settings.cache_check_every == 0:
            await asyncio.to_thread(
                cache.enforce_limit,
                self._settings.cache_dir,
                self._settings.cache_max_mb,
            )
        return data

    async def _thu_lai(self, provider: Provider, text: str, ten: str) -> bytes:
        last: BaseException | None = None
        for lan, cho in enumerate(_RETRY_DELAYS):
            if cho:
                await asyncio.sleep(cho)
            try:
                async with self._sem:
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
                    ten, lan + 1, len(_RETRY_DELAYS), type(exc).__name__, exc,
                )
        raise TTSError(
            f"{ten} thất bại sau {len(_RETRY_DELAYS)} lần thử: "
            f"{type(last).__name__}: {last}"
        )
