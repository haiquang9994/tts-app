"""Cache trên đĩa. Module này chỉ biết tới hệ thống file.

Dùng cho cả audio (`.mp3`) lẫn bản dịch (`.txt`): cùng một cách ghi nguyên tử
và cùng một ngân sách dung lượng, chỉ khác đuôi file.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_CLEANUP_TARGET_RATIO = 0.8


def cache_key(final_text: str, voice: str, rate: str) -> str:
    # voice và rate nằm trong key vì đổi giọng hay tốc độ thì ra file khác.
    raw = f"{final_text}|{voice}|{rate}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def path_for(cache_dir: Path, key: str, suffix: str = ".mp3") -> Path:
    return cache_dir / f"{key}{suffix}"


def read(cache_dir: Path, key: str, suffix: str = ".mp3") -> bytes | None:
    try:
        data = path_for(cache_dir, key, suffix).read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    # File rỗng coi như không có: nó là dấu vết của một lần ghi hỏng.
    return data or None


def write(cache_dir: Path, key: str, data: bytes, suffix: str = ".mp3") -> None:
    """Ghi nguyên tử: ra file tạm rồi os.replace.

    Tiến trình chết giữa chừng chỉ để lại file .tmp vô hại, không bao giờ
    để lại MP3 hỏng trong cache.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / f"{key}.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path_for(cache_dir, key, suffix))
    finally:
        tmp.unlink(missing_ok=True)


def cleanup_tmp(cache_dir: Path) -> int:
    """Dọn file .tmp mồ côi. Gọi lúc khởi động."""
    removed = 0
    for p in cache_dir.glob("*.tmp"):
        try:
            p.unlink()
            removed += 1
        except OSError:
            log.warning("Không xoá được file tạm %s", p)
    return removed


def enforce_limit(
    cache_dir: Path, max_mb: int, suffixes: tuple[str, ...] = (".mp3", ".txt")
) -> int:
    """Xoá file cũ nhất cho tới khi tổng dung lượng còn 80% ngưỡng.

    Quét cả bản dịch: chúng nhỏ hơn audio hàng nghìn lần nên hầu như không
    chiếm chỗ, nhưng bỏ ra ngoài ngân sách thì không có gì dọn chúng cả.
    """
    limit = max_mb * 1024 * 1024
    entries = []
    total = 0
    for suffix in suffixes:
        for p in cache_dir.glob(f"*{suffix}"):
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, p))
            total += st.st_size

    if total <= limit:
        return 0

    target = int(limit * _CLEANUP_TARGET_RATIO)
    entries.sort()
    removed = 0
    for _, size, p in entries:
        if total <= target:
            break
        try:
            p.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    log.info("Dọn cache: xoá %d file, còn %d byte", removed, total)
    return removed
