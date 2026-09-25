"""Bảo vệ khỏi lỗi đã làm hỏng ảnh trên production.

COPY của Docker giữ nguyên mode của file nguồn. Một file lỡ mang mode 640 sẽ
khiến container chạy non-root không đọc được: StaticFiles gửi 200 kèm
Content-Length rồi đóng kết nối không có thân phản hồi, và Cloudflare trả 520.

Test đơn vị thường không bắt được vì nó chạy bằng chính user sở hữu file.
Kiểm tra thẳng bit quyền mới là thứ chặn được nguyên nhân gốc.
"""
from __future__ import annotations

import stat

import pytest

from app.main import STATIC_DIR

TEP_TINH = sorted(p for p in STATIC_DIR.rglob("*") if p.is_file())


def test_all_required_static_files_exist():
    ten = {p.name for p in TEP_TINH}
    assert {"index.html", "about.html", "app.js", "style.css", "theme.js"} <= ten
    assert {"play.png", "pause.png", "end.png", "check.png", "remove.png"} <= ten


@pytest.mark.parametrize("path", TEP_TINH, ids=lambda p: p.name)
def test_every_static_file_is_world_readable(path):
    mode = path.stat().st_mode
    assert mode & stat.S_IROTH, (
        f"{path} không cho 'other' đọc (mode {oct(stat.S_IMODE(mode))}). "
        "Container chạy uid 1001:33 sẽ không đọc được -> Cloudflare trả 520."
    )


@pytest.mark.parametrize("path", TEP_TINH, ids=lambda p: p.name)
def test_no_static_file_is_empty(path):
    assert path.stat().st_size > 0
