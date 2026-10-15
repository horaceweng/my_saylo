"""On-demand running: the server only exits when nothing would be cut short by it."""

import time
import types

from app import ondemand
from app.ondemand import Activity
from app.services import compute, pipeline


def test_requests_are_counted_and_end_the_idle_time(anon_client):
    Activity.last_seen = time.monotonic() - 3600
    assert anon_client.get("/api/health").status_code == 200
    assert Activity.in_flight == 0
    assert ondemand.idle_for() < 5


def test_a_request_being_answered_is_busy(monkeypatch):
    monkeypatch.setattr(Activity, "in_flight", 1)
    Activity.last_seen = time.monotonic() - 3600
    assert ondemand.busy()
    assert ondemand.idle_for() == 0.0


def test_a_media_job_is_busy(monkeypatch):
    assert not ondemand.busy()
    monkeypatch.setattr(pipeline, "_queued", {7})
    assert pipeline.busy()
    assert ondemand.busy()


def test_a_local_model_in_use_is_busy():
    with compute.heavy.hold("tts"):
        assert ondemand.busy()
    assert not ondemand.busy()


def test_watch_stops_the_server_only_when_idle(monkeypatch):
    monkeypatch.setattr(ondemand.time, "sleep", lambda s: None)
    server = types.SimpleNamespace(should_exit=False)
    monkeypatch.setattr(ondemand, "idle_for", iter([10.0, 0.0, 901.0]).__next__)
    ondemand._watch(server, idle=900, check=30)
    assert server.should_exit


def test_not_started_by_launchd():
    assert ondemand.launchd_socket() is None
