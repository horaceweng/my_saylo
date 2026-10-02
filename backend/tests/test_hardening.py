import pytest
from fastapi.routing import APIRoute
from sqlmodel import select

from app.config import settings
from app.main import app
from app.models import Media, Segment, UsageEvent, User
from app.services import usage

OPEN_TO_ANYONE = {("POST", "/api/auth/login"), ("POST", "/api/auth/register"), ("POST", "/api/auth/logout"), ("GET", "/api/health")}


def api_routes():
    """Every (method, path) the app answers, whether it was added directly or through include_router."""
    for top in app.routes:
        for route in (top.original_router.routes if hasattr(top, "original_router") else [top]):
            if isinstance(route, APIRoute) and route.path.startswith("/api/"):
                for method in route.methods - {"HEAD", "OPTIONS"}:
                    yield method, route.path


def fill(path):
    return path.replace("{target}", "llm").replace("{path:path}", "x").replace("{word}", "hello").replace("{root}", "spic").replace("{chapter_idx}", "0") \
        .replace("{segment_id}", "1").replace("{recording_id}", "1").replace("{phrase_id}", "1").replace("{paragraph_id}", "1") \
        .replace("{media_id}", "1").replace("{book_id}", "1").replace("{feed_id}", "1").replace("{channel_id}", "1").replace("{user_id}", "1")


def test_every_api_route_asks_for_a_login(anon_client):
    checked = 0
    for method, path in api_routes():
        if (method, path) in OPEN_TO_ANYONE:
            continue
        res = anon_client.request(method, fill(path))
        assert res.status_code == 401, (method, path, res.status_code)
        checked += 1
    assert checked > 40  # the walk really covered the API


ADMIN_ONLY = lambda method, path: path.startswith("/api/admin/") or path.startswith("/api/settings") or (
    method == "DELETE" and path in ("/api/media/{media_id}", "/api/books/{book_id}", "/api/news/feeds/{feed_id}", "/api/podcasts/channels/{channel_id}")
)


def test_every_admin_route_refuses_ordinary_users(user_client):
    checked = 0
    for method, path in api_routes():
        if ADMIN_ONLY(method, path):
            res = user_client.request(method, fill(path))
            assert res.status_code == 403, (method, path, res.status_code)
            checked += 1
    assert checked >= 12


def test_the_api_description_is_not_public(anon_client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        res = anon_client.get(path)
        assert '"paths"' not in res.text and "swagger" not in res.text.lower() and "redoc" not in res.text.lower(), path


def test_a_large_json_body_is_refused_before_it_is_read(client, anon_client):
    big = {"username": "x" * (2 * 1024 * 1024), "password": "y"}
    assert anon_client.post("/api/auth/login", json=big).status_code == 413
    assert client.post("/api/phrases", json={"text": "hi", "note": "n" * (2 * 1024 * 1024)}).status_code == 413


def test_a_body_without_a_length_is_counted_as_it_arrives(client):
    def chunks():
        for _ in range(40):
            yield b"x" * 65536  # 2.5 MB in pieces, no Content-Length

    res = client.post("/api/phrases", content=chunks(), headers={"content-type": "application/json"})
    assert res.status_code == 413


def test_upload_ceilings_follow_the_account(make_client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    monkeypatch.setattr("app.routers.podcasts.pipeline.enqueue", lambda media_id: None)
    body = b"ID3" + b"\0" * (3 * 1024 * 1024)
    res = make_client("alice").post("/api/podcasts/upload", files={"file": ("a.mp3", body)})
    assert res.status_code == 413 and "1 MB" in res.json()["detail"]
    assert make_client("root", admin=True).post("/api/podcasts/upload", files={"file": ("a.mp3", body)}).status_code == 200
    assert make_client().post("/api/podcasts/upload", files={"file": ("a.mp3", body)}).status_code == 413  # not logged in: the user ceiling
    assert not list((tmp_path / "audio").glob("upload_*.mp3")) or len(list((tmp_path / "audio").glob("upload_*.mp3"))) == 1  # only the admin's file


def test_guessing_one_account_from_many_addresses_is_slowed_down(anon_client, make_client, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app as the_app

    make_client("alice")
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 4)  # the sign-in that created the account counted as one
    proxy = TestClient(the_app, client=("127.0.0.1", 5000))  # the Funnel proxy: the forwarded address is believed
    codes = [proxy.post("/api/auth/login", json={"username": "Alice", "password": "wrong-password"}, headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_ordinary_users_may_retry_only_failed_jobs_and_never_start_over(user_client, client, session, monkeypatch):
    queued = []
    monkeypatch.setattr("app.routers.media.pipeline.enqueue", queued.append)
    running = Media(source_url="u", external_id="aaaaaaaaaaa", title="R", status="transcribing")
    failed = Media(source_url="v", external_id="bbbbbbbbbbb", title="F", status="error", error="boom")
    session.add_all([running, failed])
    session.commit()
    seg = Segment(media_id=failed.id, idx=0, start=0, end=1, text="kept")
    session.add(seg)
    session.commit()
    assert user_client.post(f"/api/media/{running.id}/retry").status_code == 200 and queued == []  # nothing is queued twice
    assert user_client.post(f"/api/media/{failed.id}/retry?restart=true").status_code == 403
    assert session.exec(select(Segment).where(Segment.media_id == failed.id)).first() is not None
    assert user_client.post(f"/api/media/{failed.id}/retry").status_code == 200 and queued == [failed.id]
    assert client.post(f"/api/media/{running.id}/retry").status_code == 200 and queued == [failed.id, running.id]  # an admin may


def test_new_speech_counts_as_an_ai_use_but_a_repeat_does_not(user_client, session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.services.tts.problems", lambda: [])

    def fake_make(text, voice, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"mp3")
        return target

    monkeypatch.setattr("app.services.tts._make", fake_make)
    monkeypatch.setattr(settings, "quota_ai_requests_per_day", 2)
    say = lambda text: user_client.post("/api/tts/speak", json={"text": text, "voice": "af_heart"}).status_code  # noqa: E731
    assert say("one") == 200 and say("one") == 200  # the second is served from disk
    assert say("two") == 200
    assert say("three") == 429
    assert say("   ") == 400  # refused before anything is counted
    alice = session.exec(select(User).where(User.username == "alice")).one()
    assert usage.used_today(session, alice.id, usage.AI) == 2
