from collections import namedtuple

import pytest

from app.config import settings
from app.services import disk

Usage = namedtuple("Usage", "total used free")
real_free_bytes = disk.free_bytes  # conftest swaps disk.free_bytes for every test; this is the real one


def test_imports_are_refused_with_507_when_the_disk_is_nearly_full(user_client, client, monkeypatch):
    monkeypatch.setattr(disk, "free_bytes", lambda: 5 * disk.GB)
    for who in (user_client, client):  # everyone, the admin too
        res = who.post("/api/media", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"})
        assert res.status_code == 507 and "磁碟空間不足" in res.json()["detail"] and "5.0 GB" in res.json()["detail"]
        assert who.post("/api/podcasts", json={"audio_url": "https://example.com/a.mp3", "title": "t"}).status_code == 507
        assert who.post("/api/podcasts/upload", files={"file": ("a.mp3", b"x")}).status_code == 507
        assert who.post("/api/books/upload", files={"file": ("a.txt", b"hello")}).status_code == 507
        assert who.post("/api/books/gutenberg", json={"id": 11}).status_code == 507


def test_the_threshold_is_configurable_and_exactly_at_it_is_fine(monkeypatch):
    monkeypatch.setattr(disk, "free_bytes", lambda: 20 * disk.GB)
    disk.require_space()
    monkeypatch.setattr(settings, "min_free_disk_gb", 30)
    with pytest.raises(Exception) as e:
        disk.require_space()
    assert e.value.status_code == 507 and "30 GB" in e.value.detail


def test_with_enough_room_a_book_upload_still_works(user_client):
    assert user_client.post("/api/books/upload", files={"file": ("a.txt", b"Hello there. " * 50)}).status_code != 507


def test_free_space_is_read_from_shutil_disk_usage_for_the_data_volume(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(disk.shutil, "disk_usage", lambda p: seen.append(p) or Usage(100 * disk.GB, 90 * disk.GB, 10 * disk.GB))
    assert real_free_bytes() == 10 * disk.GB and disk.is_low() is False  # is_low uses the (big) patched value
    assert seen == [tmp_path]


def test_admin_page_shows_data_size_and_free_space_and_caches_the_walk(client, user_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "a.mp3").write_bytes(b"x" * 1000)
    (tmp_path / "app.sqlite").write_bytes(b"y" * 500)
    monkeypatch.setattr(disk, "free_bytes", lambda: 50 * disk.GB)
    body = client.get("/api/admin/disk").json()
    assert body["data_bytes"] == 1500 and body["free_bytes"] == 50 * disk.GB and body["low"] is False
    (tmp_path / "audio" / "b.mp3").write_bytes(b"z" * 1000)
    assert client.get("/api/admin/disk").json()["data_bytes"] == 1500  # cached
    monkeypatch.setattr(disk.time, "monotonic", lambda t=disk.time.monotonic(): t + disk.SIZE_CACHE_SECONDS + 1000)
    assert client.get("/api/admin/disk").json()["data_bytes"] == 2500
    monkeypatch.setattr(disk, "free_bytes", lambda: 1 * disk.GB)
    assert client.get("/api/admin/disk").json()["low"] is True
    assert user_client.get("/api/admin/disk").status_code == 403
