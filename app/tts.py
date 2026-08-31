"""Sinh audio từ văn bản: gọi edge-tts, retry, giới hạn đồng thời, single-flight.

Module này không biết gì về HTTP. Muốn đổi sang nhà cung cấp TTS khác
(Piper, gTTS...) thì chỉ cần thay `edge_provider` — phần còn lại của app
chỉ gọi qua `Synthesizer.get_audio`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import edge_tts

from . import cache
from .config import Settings

log = logging.getLogger(__name__)

# Độ trễ trước mỗi lần thử. Phần tử đầu là 0 vì lần đầu không chờ.
# Test monkeypatch giá trị này để khỏi phải chờ thật.
_RETRY_DELAYS: tuple[float, ...] = (0.0, 0.5, 1.5)

Provider = Callable[[str, str, str], Awaitable[bytes]]


class TTSError(RuntimeError):
    """Nhà cung cấp TTS không trả về được audio."""


async def edge_provider(text: str, voice: str, rate: str) -> bytes:
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
    def __init__(self, settings: Settings, provider: Provider = edge_provider) -> None:
        self._settings = settings
        self._provider = provider
        self._sem = asyncio.Semaphore(settings.tts_max_concurrency)
        self._inflight: dict[str, asyncio.Future] = {}
        self._writes = 0

    async def get_audio(self, final_text: str, voice: str, rate: str) -> tuple[str, bytes]:
        key = cache.cache_key(final_text, voice, rate)

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
            data = await self._produce(final_text, voice, rate, key)
        except BaseException as exc:
            fut.set_exception(exc)
            fut.exception()  # đánh dấu đã lấy, tránh cảnh báo lúc dọn rác
            raise
        else:
            fut.set_result(data)
            return key, data
        finally:
            self._inflight.pop(key, None)

    async def _produce(self, text: str, voice: str, rate: str, key: str) -> bytes:
        last: BaseException | None = None
        for lan, cho in enumerate(_RETRY_DELAYS):
            if cho:
                await asyncio.sleep(cho)
            try:
                async with self._sem:
                    data = await asyncio.wait_for(
                        self._provider(text, voice, rate),
                        timeout=self._settings.tts_timeout_seconds,
                    )
                break
            except Exception as exc:
                # Bắt rộng ở đúng ranh giới gọi ra ngoài. Không thu hẹp thành
                # OSError được: EdgeTTSException và aiohttp.ClientError đều kế
                # thừa thẳng Exception, nên danh sách hẹp làm retry không bao
                # giờ chạy cho đúng kiểu hỏng phổ biến nhất.
                # CancelledError kế thừa BaseException nên không bị nuốt ở đây.
                last = exc
                log.warning(
                    "Gọi TTS hỏng lần %d/%d: %s: %s",
                    lan + 1, len(_RETRY_DELAYS), type(exc).__name__, exc,
                )
        else:
            raise TTSError(
                f"TTS thất bại sau {len(_RETRY_DELAYS)} lần thử: "
                f"{type(last).__name__}: {last}"
            )

        cache.write(self._settings.cache_dir, key, data)
        self._writes += 1
        if self._writes % self._settings.cache_check_every == 0:
            await asyncio.to_thread(
                cache.enforce_limit,
                self._settings.cache_dir,
                self._settings.cache_max_mb,
            )
        return data
