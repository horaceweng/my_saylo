import asyncio
from urllib.parse import unquote

import pytest
from fastapi import FastAPI

from app.config import settings
from app.frontend import mount_frontend
from app.models import Media, Recording, Segment
from app.services import files


def raw_get(app: FastAPI, raw_path: str) -> tuple[int, bytes]:
    """Send a request whose path reaches the app exactly as written: a real HTTP client tidies "/a/../b" before sending."""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http", "path": unquote(raw_path),
        "raw_path": raw_path.encode(), "query_string": b"", "headers": [(b"host", b"t")], "client": ("1.2.3.4", 1), "server": ("t", 80),
    }
    out = {"status": 0, "body": b""}

    async def run():
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                await asyncio.sleep(3600)
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                out["status"] = message["status"]
            elif message["type"] == "http.response.body":
                out["body"] += message.get("body", b"")

        await app(scope, receive, send)

    asyncio.run(run())
    return out["status"], out["body"]


@pytest.fixture
def site(tmp_path):
    dist = tmp_path / "site" / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>APP</html>")
    (dist / "assets" / "app.js").write_text("console.log('js')")
    (tmp_path / "site" / "backend" / "data").mkdir(parents=True)
    (tmp_path / "site" / "backend" / ".env").write_text("CLOUD_API_KEY=sk-very-secret")
    (tmp_path / "site" / "backend" / "data" / "app.sqlite").write_bytes(b"SQLite format 3 secret rows")
    (tmp_path / "site" / "frontend" / "package.json").write_text('{"name": "secret-package"}')
    app = FastAPI()
    mount_frontend(app, dist)
    return app


ATTEMPTS = [
    "/../.env", "/%2e%2e/backend/.env", "/%2e%2e/%2e%2e/backend/.env", "/api/../data/app.sqlite", "/api/%2e%2e/data/app.sqlite",
    "/../backend/data/app.sqlite", "/..%2fbackend%2fdata%2fapp.sqlite", "/assets/../../backend/.env", "/assets/%2e%2e/%2e%2e/package.json",
    "//etc/passwd", "/etc/passwd", "/%2fetc%2fpasswd", "/%00", "/index.html%00.png", "/..\\backend\\.env", "/....//backend/.env", "/.env",
    "/../package.json", "/backend/.env", "/.git/config",
]


@pytest.mark.parametrize("raw", ATTEMPTS)
def test_nothing_outside_the_build_folder_is_ever_sent(site, raw):
    status, body = raw_get(site, raw)
    for secret in (b"sk-very-secret", b"SQLite format", b"secret-package", b"root:"):
        assert secret not in body, raw
    assert status in (200, 404), raw  # the page itself (200) or "not found", never a crash
    if status == 200:
        assert b"APP" in body


@pytest.mark.parametrize("raw", [a for a in ATTEMPTS if a not in ("/etc/passwd", "/backend/.env/x", "/%2fetc%2fpasswd")])
def test_every_attempt_to_reach_a_file_is_not_found(site, raw):
    assert raw_get(site, raw)[0] == 404, raw


def test_addresses_of_the_app_still_get_the_page(site):
    for raw in ("/", "/videos/3", "/news", "/books/7", "/library"):
        status, body = raw_get(site, raw)
        assert status == 200 and b"APP" in body, raw


def test_api_paths_are_never_answered_with_the_page(site):
    for raw in ("/api/../data/app.sqlite", "/api/nothing", "/api"):
        assert raw_get(site, raw)[0] == 404


def test_the_real_app_hides_the_database_and_the_key_file_too():
    from app.main import app

    for raw in ("/../.env", "/%2e%2e/backend/.env", "/api/../data/app.sqlite", "/data/app.sqlite", "/backend/data/app.sqlite"):
        status, body = raw_get(app, raw)
        assert b"SQLite format" not in body and b"CLOUD_API_KEY" not in body, raw
        assert status in (200, 404), raw


def test_inside_only_accepts_real_files_in_the_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "a.mp3").write_bytes(b"x")
    (tmp_path / "secret.txt").write_text("s")
    (tmp_path / "audio" / "link.mp3").symlink_to(tmp_path / "secret.txt")
    assert files.inside(tmp_path / "audio" / "a.mp3", "audio")
    assert files.inside(str(tmp_path / "audio" / ".." / "audio" / "a.mp3"), "audio")
    for bad in (tmp_path / "secret.txt", tmp_path / "audio" / "../secret.txt", tmp_path / "audio" / "link.mp3", tmp_path / "audio", "/etc/passwd", "", None, "a\0b"):
        assert files.inside(bad, "audio") is None, bad
    assert files.inside(tmp_path / "audio" / "a.mp3", "recordings") is None


def test_rows_pointing_outside_their_folder_serve_nothing(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "audio").mkdir()
    (tmp_path / "recordings").mkdir()
    outside = tmp_path / "app.sqlite"
    outside.write_bytes(b"database")
    media = Media(kind="podcast", source_url="u", title="t", audio_path=str(outside))
    session.add(media)
    session.commit()
    seg = Segment(media_id=media.id, idx=0, start=0, end=1, text="Hello")
    session.add(seg)
    session.commit()
    rec = Recording(segment_id=seg.id, user_id=1, file_path=str(outside), duration=1, score=1, heard_text="", diff_json="[]")
    session.add(rec)
    session.commit()
    assert client.get(f"/api/media/{media.id}/audio").status_code == 404
    assert client.get(f"/api/segments/{seg.id}/audio").status_code == 404
    assert client.get(f"/api/recordings/{rec.id}/audio").status_code == 404
    assert client.delete(f"/api/recordings/{rec.id}").status_code == 200 and outside.exists()  # the row goes, the stray file is not touched
    assert client.delete(f"/api/media/{media.id}").status_code == 200 and outside.exists()


def test_a_recording_is_only_served_to_its_owner(user_client, other_client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    folder = tmp_path / "recordings" / "1"
    folder.mkdir(parents=True)
    (folder / "r.wav").write_bytes(b"RIFF")
    media = Media(kind="podcast", source_url="u", title="t")
    session.add(media)
    session.commit()
    seg = Segment(media_id=media.id, idx=0, start=0, end=1, text="Hello")
    session.add(seg)
    session.commit()
    from app.models import User
    from sqlmodel import select

    alice = session.exec(select(User).where(User.username == "alice")).one()
    rec = Recording(segment_id=seg.id, user_id=alice.id, file_path=str(folder / "r.wav"), duration=1, score=1, heard_text="", diff_json="[]")
    session.add(rec)
    session.commit()
    assert user_client.get(f"/api/recordings/{rec.id}/audio").status_code == 200
    assert other_client.get(f"/api/recordings/{rec.id}/audio").status_code == 404
    assert other_client.delete(f"/api/recordings/{rec.id}").status_code == 404
    assert (folder / "r.wav").exists()


def test_settings_never_contain_a_whole_key(client, monkeypatch):
    keys = {"cloud_api_key": "sk-cloud-secret-0123456789", "stt_api_key": "gsk-stt-secret-9876543210", "short": "abc123"}
    monkeypatch.setattr(settings, "cloud_api_key", keys["cloud_api_key"])
    monkeypatch.setattr(settings, "stt_api_key", keys["stt_api_key"])
    monkeypatch.setattr("app.services.app_settings.installed_llm_models", lambda client=None: [])
    text = client.get("/api/settings").text
    for key in (keys["cloud_api_key"], keys["stt_api_key"]):
        assert key not in text and key[:-4] not in text and key[:10] not in text
    assert client.get("/api/settings").json()["cloud_key"].endswith("0123456789"[-4:])
    monkeypatch.setattr(settings, "cloud_api_key", keys["short"])
    assert keys["short"][:-4] not in client.get("/api/settings").json()["cloud_key"]  # a short key shows nothing of itself
    assert "key" not in client.get("/api/health").text.lower().replace("cloud_configured", "")
