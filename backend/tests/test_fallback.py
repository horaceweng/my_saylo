import json
import sys
import types

import httpx
import pytest
from pydantic import BaseModel
from sqlmodel import Session, select

from app import db
from app.config import settings
from app.models import UsageEvent
from app.services import compute, llm, transcribe, usage
from app.services.cloud_stt import CloudSTTError
from app.services.llm import FallbackProvider, LLMError


class Answer(BaseModel):
    value: int


class Scripted:
    """A provider that plays back replies; an Exception in the list is raised."""

    def __init__(self, replies, name="x"):
        self.replies, self.name, self.calls = list(replies), name, 0

    async def chat(self, system, user, *, json_mode=False):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def stream(self, system, user, *, json_mode=False):
        self.calls += 1
        for r in self.replies.pop(0):
            if isinstance(r, Exception):
                raise r
            yield r


def events(kind):
    with Session(db.engine) as s:
        return s.exec(select(UsageEvent).where(UsageEvent.kind == kind)).all()


async def test_a_cloud_429_is_answered_by_the_local_model_and_counted():
    cloud, local = Scripted([LLMError("雲端服務的速率或額度已達上限")]), Scripted(["from local"])
    p = FallbackProvider(cloud, local_factory=lambda: local)
    assert await p.chat("s", "u") == "from local"
    assert len(events(usage.FALLBACK_LLM)) == 1 and events(usage.FALLBACK_LLM)[0].user_id is None


async def test_after_a_failure_the_cloud_is_skipped_for_a_while():
    cloud, local = Scripted([LLMError("HTTP 503")]), Scripted(["a", "b"])
    await FallbackProvider(cloud, local_factory=lambda: local).chat("s", "u")
    again = FallbackProvider(cloud, local_factory=lambda: local)
    assert await again.chat("s", "u") == "b" and cloud.calls == 1  # not asked a second time
    assert len(events(usage.FALLBACK_LLM)) == 2


async def test_a_working_cloud_never_touches_the_local_model():
    cloud, local = Scripted(["cloud"]), Scripted([])
    assert await FallbackProvider(cloud, local_factory=lambda: local).chat("s", "u") == "cloud"
    assert local.calls == 0 and events(usage.FALLBACK_LLM) == []


async def test_json_that_stays_invalid_falls_back_to_the_local_model():
    cloud, local = Scripted(["nope", "still nope"]), Scripted(['{"value": 4}'])
    got = await llm.chat_json(FallbackProvider(cloud, local_factory=lambda: local), "s", "u", Answer)
    assert got.value == 4 and cloud.calls == 2 and len(events(usage.FALLBACK_LLM)) == 1


async def test_the_local_model_is_the_last_resort():
    cloud, local = Scripted([LLMError("down")]), Scripted(["bad", "worse"])
    with pytest.raises(LLMError, match="JSON"):
        await llm.chat_json(FallbackProvider(cloud, local_factory=lambda: local), "s", "u", Answer)
    assert len(events(usage.FALLBACK_LLM)) == 1  # one fallback, not a second one for the same question


async def test_a_stream_that_fails_before_any_text_continues_on_the_local_model():
    cloud, local = Scripted([[LLMError("timeout")]]), Scripted([["lo", "cal"]])
    p = FallbackProvider(cloud, local_factory=lambda: local)
    assert "".join([c async for c in p.stream("s", "u")]) == "local"


async def test_a_stream_that_fails_half_way_is_not_restarted():
    cloud, local = Scripted([["par", LLMError("cut")]]), Scripted([["x"]])
    got = []
    with pytest.raises(LLMError):
        async for c in FallbackProvider(cloud, local_factory=lambda: local).stream("s", "u"):
            got.append(c)
    assert got == ["par"] and local.calls == 0


def test_the_fallback_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "cloud")
    monkeypatch.setattr(settings, "fallback_local", False)
    assert isinstance(llm.make_provider(), llm.OpenAICompatProvider)


async def test_cloud_http_errors_become_fallbacks(monkeypatch):
    """The real cloud provider: a 429 and a connection error both end up at the local model."""
    real = httpx.AsyncClient
    monkeypatch.setattr(settings, "cloud_base_url", "https://zen.example/v1")
    monkeypatch.setattr(settings, "cloud_model", "free-1")
    for handler in (lambda r: httpx.Response(429, json={}), lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))):
        llm.cloud_cooldown.reset()
        monkeypatch.setattr(llm.httpx, "AsyncClient", lambda handler=handler, **kw: real(transport=httpx.MockTransport(handler), **kw))
        local = Scripted(["local answer"])
        assert await FallbackProvider(llm.OpenAICompatProvider(), local_factory=lambda: local).chat("s", "u") == "local answer"


# ---- local model memory ---------------------------------------------------------------------

async def test_ollama_is_told_to_drop_its_model_soon_and_can_be_unloaded(monkeypatch):
    sent = []
    real = httpx.AsyncClient

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "hi"}})

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "local_keep_alive_seconds", 45)
    assert await llm.OllamaProvider(model="m1").chat("s", "u") == "hi"
    assert sent[0]["keep_alive"] == "45s"
    posts = []
    monkeypatch.setattr(llm.httpx, "post", lambda url, json, timeout: posts.append((url, json)))
    llm.unload_ollama()
    assert posts == [(f"{settings.ollama_base_url}/api/generate", {"model": "m1", "keep_alive": 0})]
    llm.unload_ollama()
    assert len(posts) == 1  # nothing left to unload


async def test_whisper_asks_ollama_to_unload_first_and_frees_its_own_memory_after(monkeypatch):
    order = []
    fake = types.ModuleType("mlx_whisper")
    fake.transcribe = lambda audio, **kw: (order.append("whisper ran"), {"segments": []})[1]
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    monkeypatch.setattr(llm, "_loaded", {(settings.ollama_base_url, "qwen")})
    monkeypatch.setattr(llm.httpx, "post", lambda url, json, timeout: order.append(f"unload {json['model']}"))
    monkeypatch.setattr(transcribe, "_schedule_idle_release", lambda: None)
    cleared = []
    monkeypatch.setattr(transcribe, "clear_mlx_cache", lambda: cleared.append(1))

    async with compute.heavy.ahold("ollama"):
        pass
    transcribe.run_whisper("a.wav")
    assert order == ["unload qwen", "whisper ran"] and cleared == [1]

    freed = []
    monkeypatch.setitem(compute.heavy._unloaders, "whisper", lambda: freed.append(1))
    async with compute.heavy.ahold("ollama"):  # the next local LLM call drops the whisper model
        pass
    assert freed == [1]


def test_freeing_mlx_memory_is_a_no_op_when_mlx_was_never_loaded(monkeypatch):
    monkeypatch.delitem(sys.modules, "mlx.core", raising=False)
    monkeypatch.delitem(sys.modules, "mlx_whisper.transcribe", raising=False)
    transcribe.release_whisper_memory()  # must not import anything


# ---- speech recognition -----------------------------------------------------------------------

def test_cloud_speech_recognition_failing_falls_back_to_local_whisper(monkeypatch):
    monkeypatch.setattr(settings, "stt_backend", "cloud")
    monkeypatch.setattr(settings, "fallback_local", True)
    from app.services import cloud_stt

    def broken(samples):
        raise CloudSTTError("語音辨識服務的速率或額度已達上限")

    monkeypatch.setattr(cloud_stt, "transcribe_samples", broken)
    local = []
    monkeypatch.setattr(transcribe, "run_whisper", lambda samples, **kw: (local.append(1), {"segments": []})[1])
    assert transcribe.recognise([0.0]) == {"segments": []}
    assert transcribe.recognise([0.0]) == {"segments": []}  # the second piece skips the cloud
    assert len(local) == 2 and len(events(usage.FALLBACK_STT)) == 2


def test_without_the_fallback_a_cloud_failure_is_an_error(monkeypatch):
    monkeypatch.setattr(settings, "stt_backend", "cloud")
    monkeypatch.setattr(settings, "fallback_local", False)
    from app.services import cloud_stt

    monkeypatch.setattr(cloud_stt, "transcribe_samples", lambda s: (_ for _ in ()).throw(CloudSTTError("x")))
    with pytest.raises(CloudSTTError):
        transcribe.recognise([0.0])
