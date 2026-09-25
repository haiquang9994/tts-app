"""Cloudflare cache tài nguyên tĩnh nhiều giờ.

Không gắn phiên bản vào URL thì after mỗi lần deploy người dùng nhận HTML mới
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


def test_every_asset_in_html_is_versioned(html):
    khong_phien_ban = re.findall(r'/static/[A-Za-z0-9_./-]+?\.(?:js|css|png)(?!\?v=)', html)
    assert khong_phien_ban == [], f"còn tài nguyên chưa gắn phiên bản: {khong_phien_ban}"


def test_js_and_css_get_versions(html):
    ten = {m[0] for m in _V.findall(html)}
    assert "app.js" in ten
    assert "style.css" in ten
    assert "theme.js" in ten


def test_version_matches_real_content_hash(html):
    for ten, ban in _V.findall(html):
        assert ban == main._content_hash(main.STATIC_DIR / ten)


def test_version_changes_when_content_changes(tmp_path):
    p = tmp_path / "x.js"
    p.write_bytes(b"mot")
    b1 = main._content_hash(p)
    p.write_bytes(b"hai")
    assert main._content_hash(p) != b1


def test_static_files_carry_revalidate_header():
    with TestClient(app) as client:
        res = client.get("/static/app.js")
    assert res.status_code == 200
    assert "no-cache" in res.headers.get("cache-control", "")


def test_about_page_is_versioned_too():
    with TestClient(app) as client:
        res = client.get("/about")
    assert res.status_code == 200
    assert "?v=" in res.text
