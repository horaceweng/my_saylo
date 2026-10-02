import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from app import db
from app.config import settings
from app.models import UsageEvent, User
from app.services import usage


def explain_body(n):
    return {"sentence": f"Sentence number {n}."}


@pytest.fixture
def ai(fake_llm):
    fake_llm.replies["英文老師"] = json.dumps({"translation": "譯", "structure": "S", "similar_examples": [{"en": "a", "zh": "b"}]})
    return fake_llm


# ---- the day boundary ---------------------------------------------------------------------

def test_a_day_runs_from_midnight_to_midnight_in_taipei():
    now = datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)  # 01:00 on Oct 3 in Taipei
    assert usage.day_start(now) == datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)
    assert usage.next_reset(now) == datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)
    before = datetime(2026, 10, 2, 15, 59, tzinfo=timezone.utc)  # 23:59 on Oct 2
    assert usage.day_start(before) == datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)
    assert usage.next_reset(before) == datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)


def test_yesterdays_use_does_not_count_today(session):
    user = User(username="a", password_hash="x")
    session.add(user)
    session.commit()
    old = usage.day_start() - timedelta(minutes=1)
    session.add(UsageEvent(user_id=user.id, kind=usage.AI, created_at=old))
    session.add(UsageEvent(user_id=user.id, kind=usage.AI))
    session.commit()
    assert usage.used_today(session, user.id, usage.AI) == 1


# ---- AI requests --------------------------------------------------------------------------

def test_ai_requests_stop_at_the_daily_limit_with_a_message_saying_which_and_when(user_client, ai, monkeypatch):
    monkeypatch.setattr(settings, "quota_ai_requests_per_day", 2)
    assert user_client.post("/api/ai/explain-sentence", json=explain_body(1)).status_code == 200
    assert user_client.post("/api/ai/explain-sentence", json=explain_body(2)).status_code == 200  # exactly at the limit is fine
    res = user_client.post("/api/ai/explain-sentence", json=explain_body(3))
    assert res.status_code == 429
    detail = res.json()["detail"]
    assert "AI 使用次數" in detail and "2" in detail and "重置" in detail and "台北時間" in detail
    assert int(res.headers["retry-after"]) > 0
    assert ai.calls == 2  # the refused one never reached the model


def test_an_answer_from_the_cache_is_not_counted(user_client, ai, monkeypatch):
    monkeypatch.setattr(settings, "quota_ai_requests_per_day", 1)
    for _ in range(4):
        assert user_client.post("/api/ai/explain-sentence", json=explain_body(1)).status_code == 200
    assert ai.calls == 1


def test_each_user_has_their_own_allowance_and_admins_have_none(user_client, other_client, client, ai, monkeypatch):
    monkeypatch.setattr(settings, "quota_ai_requests_per_day", 1)
    assert user_client.post("/api/ai/explain-sentence", json=explain_body(1)).status_code == 200
    assert user_client.post("/api/ai/explain-sentence", json=explain_body(2)).status_code == 429
    assert other_client.post("/api/ai/explain-sentence", json=explain_body(3)).status_code == 200
    for n in range(4, 9):
        assert client.post("/api/ai/explain-sentence", json=explain_body(n)).status_code == 200  # the admin


def test_the_streaming_explanation_is_refused_before_it_starts(user_client, monkeypatch):
    from tests.test_api import _explain_service_override

    _explain_service_override()
    monkeypatch.setattr(settings, "quota_ai_requests_per_day", 1)
    assert user_client.post("/api/ai/explain-sentence/stream", json=explain_body(1)).status_code == 200
    res = user_client.post("/api/ai/explain-sentence/stream", json=explain_body(2))
    assert res.status_code == 429 and "重置" in res.json()["detail"]
    assert user_client.post("/api/ai/explain-sentence/stream", json=explain_body(1)).status_code == 200  # cached now: free


# ---- new videos and audio length ----------------------------------------------------------

@pytest.fixture
def videos(monkeypatch):
    """Adding a video finds out its length (here from the link's last letter: a = 10 minutes, b = 100 minutes)."""
    queued = []
    monkeypatch.setattr("app.routers.media.pipeline.enqueue", queued.append)

    async def info(video_id):
        return {"title": video_id, "thumbnail": "", "duration": 6000.0 if video_id.endswith("b") else 600.0}

    monkeypatch.setattr("app.routers.media.youtube.fetch_info_async", info)
    return queued


def vid(n, kind="a"):
    return f"https://www.youtube.com/watch?v=vid{n:07d}{kind}"  # 11 characters


def test_new_media_per_day_is_limited(user_client, videos, monkeypatch):
    monkeypatch.setattr(settings, "quota_media_per_day", 2)
    assert user_client.post("/api/media", json={"url": vid(1)}).status_code == 200
    assert user_client.post("/api/media", json={"url": vid(2)}).status_code == 200
    res = user_client.post("/api/media", json={"url": vid(3)})
    assert res.status_code == 429 and "新增的影片" in res.json()["detail"] and "台北時間" in res.json()["detail"]
    assert len(videos) == 2
    # a video somebody already added is just opened: it costs nothing
    assert user_client.post("/api/media", json={"url": vid(1)}).status_code == 200


def test_audio_minutes_per_day_are_limited(user_client, videos, monkeypatch):
    monkeypatch.setattr(settings, "quota_audio_minutes_per_day", 25)
    assert user_client.post("/api/media", json={"url": vid(1)}).status_code == 200  # 10 minutes
    assert user_client.post("/api/media", json={"url": vid(2)}).status_code == 200  # 20
    res = user_client.post("/api/media", json={"url": vid(3)})  # 30 > 25
    assert res.status_code == 429 and "音訊長度" in res.json()["detail"]


def test_a_single_media_that_is_too_long_is_refused_for_users_but_not_admins(user_client, client, videos):
    res = user_client.post("/api/media", json={"url": vid(1, "b")})  # 100 minutes
    assert res.status_code == 413 and "90 分鐘" in res.json()["detail"]
    assert client.post("/api/media", json={"url": vid(1, "b")}).status_code == 200


def test_admins_are_not_limited_in_new_media(client, videos, monkeypatch):
    monkeypatch.setattr(settings, "quota_media_per_day", 1)
    for n in range(1, 4):
        assert client.post("/api/media", json={"url": vid(n)}).status_code == 200


# ---- uploads ------------------------------------------------------------------------------

def test_the_upload_size_limit_applies_to_users_only(user_client, client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.routers.podcasts.pipeline.enqueue", lambda media_id: None)
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = b"ID3" + b"\0" * (2 * 1024 * 1024)
    res = user_client.post("/api/podcasts/upload", files={"file": ("a.mp3", big)})
    assert res.status_code == 413 and "1 MB" in res.json()["detail"]
    assert not list((tmp_path / "audio").glob("upload_*"))  # nothing left behind
    assert client.post("/api/podcasts/upload", files={"file": ("a.mp3", big)}).status_code == 200


# ---- the admin page -----------------------------------------------------------------------

def test_the_users_page_lists_todays_use_per_user_and_the_fallback_counts(client, user_client, ai, session, monkeypatch):
    monkeypatch.setattr(db, "engine", session.get_bind())  # in the app both are the same database
    user_client.post("/api/ai/explain-sentence", json=explain_body(1))
    user_client.post("/api/ai/explain-sentence", json=explain_body(2))
    usage.record_system(usage.FALLBACK_LLM)
    usage.record_system(usage.FALLBACK_STT)
    usage.record_system(usage.FALLBACK_STT)
    users = {u["username"]: u for u in client.get("/api/admin/users").json()}
    assert users["alice"]["usage_today"] == {"media": 0, "audio_minutes": 0, "ai": 2}
    assert users["admin"]["usage_today"]["ai"] == 0
    overview = client.get("/api/admin/usage").json()
    assert overview["fallbacks"] == {"llm": {"today": 1, "week": 1}, "stt": {"today": 2, "week": 2}}
    assert overview["limits"] == {"media": 5, "audio_minutes": 90, "ai": 300}
    assert user_client.get("/api/admin/usage").status_code == 403
