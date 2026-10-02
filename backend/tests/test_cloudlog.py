"""Every failed cloud call is logged with its reason, whether or not the local model then takes over."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import BaseModel
from sqlmodel import Session, select

from app import db
from app.config import settings
from app.models import CloudCall
from app.services import cloud_stt, cloudlog, llm, transcribe
from app.services.cloud_stt import CloudSTTError
from app.services.llm import FallbackProvider, LLMError, OpenAICompatProvider

REAL_ASYNC, REAL_SYNC = httpx.AsyncClient, httpx.Client
FREE_TIER = {"error": {"type": "FreeTierError", "message": "FreeTierError: OpenCode's free tier can only be used from within OpenCode"}}


@pytest.fixture(autouse=True)
def cloud_settings(monkeypatch):
    for name, value in {"cloud_base_url": "https://zen.example/v1", "cloud_api_key": "sk-secret-1234", "cloud_model": "free-1",
                        "stt_base_url": "https://stt.example/v1", "stt_api_key": "gsk-secret-9876", "stt_model": "w"}.items():
        monkeypatch.setattr(settings, name, value)


def serve(monkeypatch, handler):
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: REAL_ASYNC(transport=httpx.MockTransport(handler), **kw))


def rows(service=cloudlog.LLM):
    with Session(db.engine) as s:
        return s.exec(select(CloudCall).where(CloudCall.service == service).order_by(CloudCall.id)).all()


class Local:
    async def chat(self, system, user, *, json_mode=False):
        return "local"


# ---- scrubbing ------------------------------------------------------------------------------------

def test_scrub_removes_keys_and_authorization_headers_and_shortens():
    dirty = ("Authorization: Bearer sk-live-abcdef123456 failed; sk-secret-1234 and gsk-secret-9876 leaked; "
             "https://x.example/v1?api_key=abc123xyz&b=1 {'authorization': 'Basic QWxhZGRpbjpvcGVu'} token=hunter22")
    clean = cloudlog.scrub(dirty)
    for secret in ("abcdef123456", "sk-secret-1234", "gsk-secret-9876", "abc123xyz", "QWxhZGRpbjpvcGVu", "hunter22"):
        assert secret not in clean
    assert "\n" not in cloudlog.scrub("a\nb\n\nc") and cloudlog.scrub("a\nb") == "a b"
    assert len(cloudlog.scrub("x" * 1000)) == 200


# ---- language model -------------------------------------------------------------------------------

async def test_a_403_is_logged_with_status_class_and_the_services_own_words_even_when_the_fallback_answers(monkeypatch):
    serve(monkeypatch, lambda r: httpx.Response(403, json=FREE_TIER))
    assert await FallbackProvider(OpenAICompatProvider(), local_factory=Local).chat("s", "u") == "local"
    (row,) = rows()
    assert (row.ok, row.status_code, row.error_class) == (False, 403, "http")
    assert "FreeTierError" in row.message and len(row.message) <= 200


async def test_a_failure_is_logged_when_the_fallback_is_off_too(monkeypatch):
    serve(monkeypatch, lambda r: httpx.Response(500, text="boom sk-secret-1234"))
    with pytest.raises(LLMError):
        await OpenAICompatProvider().chat("s", "u")
    (row,) = rows()
    assert (row.status_code, row.error_class) == (500, "http") and "sk-secret-1234" not in row.message and "boom" in row.message


async def test_timeouts_connection_errors_and_unusable_replies_get_their_own_class(monkeypatch):
    def timeout(r):
        raise httpx.ReadTimeout("slow")

    def down(r):
        raise httpx.ConnectError("refused")

    for handler in (timeout, down, lambda r: httpx.Response(200, json={"nope": 1}), lambda r: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})):
        serve(monkeypatch, handler)
        with pytest.raises(LLMError):
            await OpenAICompatProvider().chat("s", "u")
    assert [(r.error_class, r.status_code) for r in rows()] == [("timeout", None), ("connection", None), ("invalid_json", None), ("other", None)]


async def test_streams_log_failures_and_successes(monkeypatch):
    serve(monkeypatch, lambda r: httpx.Response(429, json={}))
    with pytest.raises(LLMError):
        async for _ in OpenAICompatProvider().stream("s", "u"):
            pass
    serve(monkeypatch, lambda r: httpx.Response(200, text='data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'))
    assert [p async for p in OpenAICompatProvider().stream("s", "u")] == ["hi"]
    assert [(r.ok, r.status_code) for r in rows()] == [(False, 429), (True, None)]


class Answer(BaseModel):
    value: int


async def test_answers_that_are_not_json_are_logged_as_invalid_json(monkeypatch):
    serve(monkeypatch, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}))
    assert await llm.chat_json(FallbackProvider(OpenAICompatProvider(), local_factory=lambda: _Json()), "s", "u", Answer) == Answer(value=1)
    failures = [r for r in rows() if not r.ok]
    assert [r.error_class for r in failures] == ["invalid_json"] and "not valid JSON" in failures[0].message


class _Json:
    async def chat(self, system, user, *, json_mode=False):
        return '{"value": 1}'


async def test_cooldown_skips_are_not_logged_as_calls(monkeypatch):
    serve(monkeypatch, lambda r: httpx.Response(403, json=FREE_TIER))
    for _ in range(4):  # the first call fails for real, the next three never reach the cloud
        await FallbackProvider(OpenAICompatProvider(), local_factory=Local).chat("s", "u")
    assert len(rows()) == 1


# ---- speech recognition ---------------------------------------------------------------------------

def stt(monkeypatch, handler, sleep=lambda s: None):
    client = REAL_SYNC(transport=httpx.MockTransport(handler))
    return lambda: cloud_stt.transcribe_mp3(b"x", client=client, sleep=sleep)


def test_stt_failures_are_logged_with_their_reason(monkeypatch):
    with pytest.raises(CloudSTTError):
        stt(monkeypatch, lambda r: httpx.Response(401, json={"error": {"message": "bad key gsk-secret-9876"}}))()
    def down(r):
        raise httpx.ConnectTimeout("t")
    with pytest.raises(CloudSTTError):
        stt(monkeypatch, down)()
    with pytest.raises(CloudSTTError):
        stt(monkeypatch, lambda r: httpx.Response(200, text="<html>"))()
    first, second, third = rows(cloudlog.STT)
    assert (first.status_code, first.error_class) == (401, "http") and "gsk-secret-9876" not in first.message and "bad key" in first.message
    assert (second.error_class, third.error_class) == ("timeout", "invalid_json")


def test_stt_failure_is_logged_with_and_without_the_fallback(monkeypatch):
    monkeypatch.setattr(settings, "stt_backend", "cloud")
    monkeypatch.setattr(cloud_stt, "encode_mp3", lambda samples: b"x")
    real = httpx.Client
    monkeypatch.setattr(cloud_stt.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"error": {"message": "no"}})), **kw))
    monkeypatch.setattr(transcribe, "run_whisper", lambda samples, **kw: {"segments": []})
    monkeypatch.setattr(settings, "fallback_local", True)
    assert transcribe.recognise([0.0]) == {"segments": []}
    monkeypatch.setattr(settings, "fallback_local", False)
    transcribe.cloud_cooldown.reset()
    with pytest.raises(CloudSTTError):
        transcribe.recognise([0.0])
    assert [r.status_code for r in rows(cloudlog.STT)] == [403, 403]


# ---- the admin page -------------------------------------------------------------------------------

def add(service=cloudlog.LLM, ok=False, status=403, cls="http", message="FreeTierError: x", ago=timedelta(0)):
    with Session(db.engine) as s:
        s.add(CloudCall(service=service, ok=ok, status_code=status, error_class=cls, message=message, created_at=datetime.now(timezone.utc) - ago))
        s.commit()


def test_overview_groups_failures_by_reason_for_today_and_the_week(client):
    add(status=429, message="slow down")
    add(status=429, message="slow down", ago=timedelta(days=3))
    add(status=None, cls="timeout", message="ReadTimeout", ago=timedelta(days=3))
    add(ok=True, status=None, cls="")
    add(service=cloudlog.STT, status=401, message="bad key")
    llm_part = client.get("/api/admin/usage").json()["cloud"]["llm"]
    by = {(r["error_class"], r["status_code"]): (r["today"], r["week"]) for r in llm_part["reasons"]}
    assert by == {("http", 429): (1, 2), ("timeout", None): (0, 1)}
    assert llm_part["calls_today"] == 2 and llm_part["last_failure"]["message"] == "slow down" and llm_part["last_failure"]["status_code"] == 429
    stt_part = client.get("/api/admin/usage").json()["cloud"]["stt"]
    assert stt_part["reasons"][0]["status_code"] == 401 and stt_part["last_failure"]["message"] == "bad key"


def test_overview_is_empty_without_failures(client):
    cloud = client.get("/api/admin/usage").json()
    assert cloud["cloud"]["llm"]["reasons"] == [] and cloud["cloud"]["llm"]["last_failure"] is None and cloud["llm_looks_disabled"] is False


def test_five_403s_in_a_row_mean_the_model_looks_disabled(client, user_client):
    for _ in range(4):
        add()
    assert client.get("/api/admin/usage").json()["llm_looks_disabled"] is False  # not enough calls yet
    add(status=500, message="FreeTierError appears in the text")  # the wording alone is enough
    assert client.get("/api/admin/usage").json()["llm_looks_disabled"] is True
    assert user_client.get("/api/admin/usage").status_code == 403


def test_a_success_among_the_last_five_calls_clears_the_warning(client):
    for _ in range(4):
        add()
    add(ok=True, status=None, cls="", message="")
    assert client.get("/api/admin/usage").json()["llm_looks_disabled"] is False
    for _ in range(5):
        add()
    assert client.get("/api/admin/usage").json()["llm_looks_disabled"] is True
    for _ in range(5):
        add(status=500, message="upstream error")  # other failures do not say the model was switched off
    assert client.get("/api/admin/usage").json()["llm_looks_disabled"] is False


def test_stt_failures_never_trigger_the_language_model_warning(client):
    for _ in range(6):
        add(service=cloudlog.STT)
    assert client.get("/api/admin/usage").json()["llm_looks_disabled"] is False
