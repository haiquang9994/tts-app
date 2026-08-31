import os
from pathlib import Path

import pytest

from app import cache


def test_key_on_dinh_va_dai_32_ky_tu():
    k1 = cache.cache_key("xin chào", "vi-VN-HoaiMyNeural", "+20%")
    k2 = cache.cache_key("xin chào", "vi-VN-HoaiMyNeural", "+20%")
    assert k1 == k2
    assert len(k1) == 32


def test_key_doi_khi_giong_hoac_toc_do_doi():
    base = cache.cache_key("xin chào", "vi-VN-HoaiMyNeural", "+20%")
    assert cache.cache_key("xin chào", "vi-VN-NamMinhNeural", "+20%") != base
    assert cache.cache_key("xin chào", "vi-VN-HoaiMyNeural", "+50%") != base


def test_read_tra_none_khi_chua_co_file(tmp_path: Path):
    assert cache.read(tmp_path, "khongtontai") is None


def test_read_tra_none_khi_file_rong(tmp_path: Path):
    (tmp_path / "rong.mp3").write_bytes(b"")
    assert cache.read(tmp_path, "rong") is None


def test_write_roi_read_tra_dung_du_lieu(tmp_path: Path):
    cache.write(tmp_path, "abc", b"du-lieu-mp3")
    assert cache.read(tmp_path, "abc") == b"du-lieu-mp3"


def test_write_tao_thu_muc_neu_chua_co(tmp_path: Path):
    target = tmp_path / "chua" / "ton" / "tai"
    cache.write(target, "abc", b"x")
    assert cache.read(target, "abc") == b"x"


def test_write_khong_de_lai_gi_khi_ghi_hong(tmp_path: Path):
    # Payload sai kiểu làm write_bytes ném lỗi trước khi kịp đổi tên.
    with pytest.raises(TypeError):
        cache.write(tmp_path, "abc", "khong-phai-bytes")

    # Không có MP3 hỏng nằm lại, và không còn file .tmp mồ côi.
    assert list(tmp_path.glob("*.mp3")) == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_dung_os_replace_de_ghi_nguyen_tu(tmp_path: Path, monkeypatch):
    # Theo dõi chứ không chặn: thay hành vi thật của os.replace trong lúc test
    # có thể làm hỏng chính pytest.
    goi = []
    that = cache.os.replace

    def spy(src, dst):
        goi.append((str(src), str(dst)))
        return that(src, dst)

    monkeypatch.setattr(cache.os, "replace", spy)
    cache.write(tmp_path, "abc", b"x")

    assert len(goi) == 1
    nguon, dich = goi[0]
    assert nguon.endswith(".tmp")
    assert dich.endswith("abc.mp3")


def test_cleanup_tmp_xoa_file_tmp_mo_coi(tmp_path: Path):
    (tmp_path / "a.tmp").write_bytes(b"x")
    (tmp_path / "b.tmp").write_bytes(b"y")
    (tmp_path / "giu.mp3").write_bytes(b"z")
    assert cache.cleanup_tmp(tmp_path) == 2
    assert (tmp_path / "giu.mp3").exists()


def test_enforce_limit_khong_lam_gi_khi_duoi_nguong(tmp_path: Path):
    (tmp_path / "a.mp3").write_bytes(b"x" * 100)
    assert cache.enforce_limit(tmp_path, max_mb=1) == 0
    assert (tmp_path / "a.mp3").exists()


def test_enforce_limit_xoa_file_cu_nhat_truoc(tmp_path: Path):
    # Ngưỡng 1MB, mục tiêu sau khi dọn là 80% = 838860 byte.
    for i, name in enumerate(["cu.mp3", "vua.mp3", "moi.mp3"]):
        p = tmp_path / name
        p.write_bytes(b"x" * 400_000)
        os.utime(p, (1000 + i, 1000 + i))

    removed = cache.enforce_limit(tmp_path, max_mb=1)

    assert removed == 1
    assert not (tmp_path / "cu.mp3").exists()
    assert (tmp_path / "vua.mp3").exists()
    assert (tmp_path / "moi.mp3").exists()
