"""Bảo vệ khỏi lỗi đã làm hỏng ảnh trên production.

File ảnh chép từ project Django cũ mang mode 640. COPY của Docker giữ nguyên
mode đó, nên container chạy non-root không đọc được: StaticFiles gửi 200 kèm
Content-Length rồi đóng kết nối không có thân phản hồi, và Cloudflare trả 520.

Test đơn vị thường không bắt được vì nó chạy bằng chính user sở hữu file.
Kiểm tra thẳng bit quyền mới là thứ chặn được nguyên nhân gốc.
"""
from __future__ import annotations

import stat

import pytest

from app.main import STATIC_DIR

TEP_TINH = sorted(p for p in STATIC_DIR.rglob("*") if p.is_file())


def test_co_du_cac_tep_tinh_can_thiet():
    ten = {p.name for p in TEP_TINH}
    assert {"index.html", "about.html", "app.js", "style.css"} <= ten
    assert {"play.png", "pause.png", "end.png", "check.png", "remove.png"} <= ten


@pytest.mark.parametrize("path", TEP_TINH, ids=lambda p: p.name)
def test_moi_tep_tinh_deu_cho_moi_user_doc(path):
    mode = path.stat().st_mode
    assert mode & stat.S_IROTH, (
        f"{path} không cho 'other' đọc (mode {oct(stat.S_IMODE(mode))}). "
        "Container chạy uid 1001:33 sẽ không đọc được -> Cloudflare trả 520."
    )


@pytest.mark.parametrize("path", TEP_TINH, ids=lambda p: p.name)
def test_khong_co_tep_tinh_nao_rong(path):
    assert path.stat().st_size > 0
