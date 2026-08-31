"""Cloudflare cache tài nguyên tĩnh nhiều giờ.

Không gắn phiên bản vào URL thì sau mỗi lần deploy người dùng nhận HTML mới
nhưng JS/CSS cũ. Đúng lỗi này đã làm trang production hỏng: index.html mới bỏ
hai dropdown, còn app.js cũ vẫn cố tìm chúng và ném TypeError.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app

_V = re.compile(r'/static/([A-Za-z0-9_./-]+?\.(?:js|css|png))\?v=([0-9a-f]{10})')


@pytest.fixture
def html():
    with TestClient(app) as client:
        return client.get("/").text


def test_moi_tai_nguyen_trong_html_deu_co_phien_ban(html):
    khong_phien_ban = re.findall(r'/static/[A-Za-z0-9_./-]+?\.(?:js|css|png)(?!\?v=)', html)
    assert khong_phien_ban == [], f"còn tài nguyên chưa gắn phiên bản: {khong_phien_ban}"


def test_co_gan_phien_ban_cho_js_va_css(html):
    ten = {m[0] for m in _V.findall(html)}
    assert "app.js" in ten
    assert "style.css" in ten


def test_phien_ban_dung_bam_noi_dung_that(html):
    for ten, ban in _V.findall(html):
        assert ban == main._bam_noi_dung(main.STATIC_DIR / ten)


def test_phien_ban_doi_khi_noi_dung_doi(tmp_path):
    p = tmp_path / "x.js"
    p.write_bytes(b"mot")
    b1 = main._bam_noi_dung(p)
    p.write_bytes(b"hai")
    assert main._bam_noi_dung(p) != b1


def test_tai_nguyen_tinh_co_header_buoc_kiem_tra_lai():
    with TestClient(app) as client:
        res = client.get("/static/app.js")
    assert res.status_code == 200
    assert "no-cache" in res.headers.get("cache-control", "")


def test_trang_about_cung_duoc_gan_phien_ban():
    with TestClient(app) as client:
        res = client.get("/about")
    assert res.status_code == 200
    assert "?v=" in res.text
