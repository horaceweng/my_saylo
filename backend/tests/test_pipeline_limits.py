import threading
import time

import pytest
from sqlmodel import Session, select

from app.config import settings
from app.models import Media, UsageEvent, User
from app.services import pipeline
from tests.test_pipeline import add_media, job, state  # noqa: F401 - `job` is a fixture


def test_a_job_that_runs_over_its_time_is_marked_failed_and_a_retry_finishes_it(job, monkeypatch):
    engine, calls = job
    mid = add_media(engine)
    monkeypatch.setattr(settings, "media_time_factor", 0)
    monkeypatch.setattr(settings, "media_time_extra_seconds", -1)  # the allowance is already used up
    pipeline.process_media(mid)
    media, _ = state(engine, mid)
    assert media.status == "error" and "處理時間太長" in media.error and "繼續處理" in media.error
    monkeypatch.setattr(settings, "media_time_factor", 3.0)  # the retry button: the same job again, with the normal allowance
    monkeypatch.setattr(settings, "media_time_extra_seconds", 600)
    pipeline.process_media(mid)
    media, segs = state(engine, mid)
    assert media.status == "ready" and len(segs) == 13 and calls["download"] == 1  # the audio was not fetched again


def test_the_allowance_grows_with_the_audio_length():
    assert pipeline.time_budget(3600) == 3600 * settings.media_time_factor + settings.media_time_extra_seconds
    assert pipeline.time_budget(3600) > pipeline.time_budget(60)


def test_waiting_jobs_know_how_many_are_ahead_of_them(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow(media_id):
        started.set()
        release.wait(5)

    monkeypatch.setattr(pipeline, "process_media", slow)
    pipeline.enqueue(911)
    assert started.wait(2)
    pipeline.enqueue(912)
    pipeline.enqueue(913)
    assert [pipeline.queue_position(i) for i in (911, 912, 913, 999)] == [0, 1, 2, 0]  # the running one counts as ahead
    release.set()
    deadline = time.time() + 3
    while pipeline.queue_position(913) and time.time() < deadline:
        time.sleep(0.01)
    assert pipeline.queue_position(913) == 0


def test_media_rows_carry_the_queue_position_while_pending(client, session, monkeypatch):
    waiting = Media(source_url="u", external_id="aaaaaaaaaaa", title="W", status="pending")
    running = Media(source_url="v", external_id="bbbbbbbbbbb", title="R", status="transcribing")
    session.add(waiting)
    session.add(running)
    session.commit()
    monkeypatch.setattr(pipeline, "queue_position", lambda media_id: 3)
    got = {m["title"]: m["queue_position"] for m in client.get("/api/media").json()}
    assert got == {"W": 3, "R": 0}


def _user(engine, admin=False):
    with Session(engine) as s:
        u = User(username="u" + str(admin), password_hash="x", is_admin=admin)
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def test_an_episode_of_unknown_length_is_counted_once_it_is_measured(job):
    engine, _ = job
    uid = _user(engine)
    with Session(engine) as s:
        m = Media(source_url="p", external_id="ccccccccccc", title="P", kind="podcast", added_by=uid)
        s.add(m)
        s.commit()
        s.refresh(m)
        mid = m.id
    pipeline._account_length(mid, 600, first_time=True)
    pipeline._account_length(mid, 600, first_time=False)  # a retry does not count it again
    with Session(engine) as s:
        rows = s.exec(select(UsageEvent).where(UsageEvent.kind == "audio_minutes")).all()
    assert [(r.user_id, r.amount) for r in rows] == [(uid, 10.0)]


def test_an_episode_over_the_length_limit_is_refused_for_users_but_not_admins(job, monkeypatch):
    engine, _ = job
    monkeypatch.setattr(settings, "max_media_minutes", 90)
    user, admin = _user(engine), _user(engine, admin=True)
    ids = {}
    with Session(engine) as s:
        for name, owner in (("user", user), ("admin", admin), ("nobody", None)):
            m = Media(source_url=name, external_id="ddddddddddd", title=name, kind="podcast", added_by=owner)
            s.add(m)
            s.commit()
            s.refresh(m)
            ids[name] = m.id
    with pytest.raises(RuntimeError, match="90 分鐘"):
        pipeline._account_length(ids["user"], 100 * 60, first_time=True)
    pipeline._account_length(ids["admin"], 100 * 60, first_time=True)
    pipeline._account_length(ids["nobody"], 100 * 60, first_time=True)  # imported in a batch: no owner to limit
