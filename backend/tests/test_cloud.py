import json

import httpx
import numpy as np
import pytest
from sqlmodel import Session

from app.config import settings
from app.models import Setting
from app.services import ai_cache, app_settings, cloud_stt, llm, transcribe
from app.services.cloud_stt import CloudSTTError
from app.services.llm import LLMError, OpenAICompatProvider


@pytest.fixture
def cloud(monkeypatch):
    """Cloud settings for one test (restored afterwards)."""
    for name, value in {"llm_backend": "cloud", "cloud_base_url": "https://api.example.com/v1/", "cloud_api_key": "sk-secret-1234",
                        "cloud_model": "tiny-model", "stt_backend": "cloud", "stt_base_url": "https://stt.example.com/v1",
                        "stt_api_key": "gsk-secret-9876", "stt_model": "whisper-x"}.items():
        monkeypatch.setattr(settings, name, value)


REAL_CLIENT = httpx.AsyncClient


def serve(monkeypatch, handler):
    """Every httpx client the provider creates talks to `handler` instead of the network."""
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_chat_sends_the_key_model_and_json_mode(cloud, monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return reply('{"a": 1}')

    serve(monkeypatch, handler)
    assert await OpenAICompatProvider().chat("sys", "hi", json_mode=True) == '{"a": 1}'
    url, auth, body = seen[0]
    assert url == "https://api.example.com/v1/chat/completions" and auth == "Bearer sk-secret-1234"
    assert body["model"] == "tiny-model" and body["response_format"] == {"type": "json_object"} and body["stream"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


async def test_a_service_that_rejects_json_mode_is_asked_again_without_it(cloud, monkeypatch):
    bodies = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(400, json={"error": {"message": "response_format not supported"}}) if "response_format" in body else reply("ok")

    serve(monkeypatch, handler)
    assert await OpenAICompatProvider().chat("s", "u", json_mode=True) == "ok"
    assert len(bodies) == 2 and "response_format" not in bodies[1]


@pytest.mark.parametrize("status,expected", [(401, "金鑰"), (404, "模型"), (429, "上限"), (402, "額度"), (503, "暫時")])
async def test_http_errors_become_readable_messages_without_the_key(cloud, monkeypatch, status, expected):
    serve(monkeypatch, lambda request: httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(LLMError) as e:
        await OpenAICompatProvider().chat("s", "u")
    assert expected in str(e.value) and "sk-secret" not in str(e.value)


async def test_a_strange_answer_and_a_network_failure_are_reported(cloud, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMError, match="格式"):
        await OpenAICompatProvider().chat("s", "u")
    serve(monkeypatch, lambda request: reply(""))
    with pytest.raises(LLMError, match="沒有回覆"):
        await OpenAICompatProvider().chat("s", "u")

    def down(request):
        raise httpx.ConnectError("offline")

    serve(monkeypatch, down)
    with pytest.raises(LLMError, match="連不上"):
        await OpenAICompatProvider().chat("s", "u")


def sse(*chunks: str) -> str:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks]
    return "".join(lines) + "data: [DONE]\n\n"


async def test_streaming_yields_the_pieces_in_order(cloud, monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(200, text=": keep-alive\n\n" + sse("Hel", "lo ", "there")))
    pieces = [p async for p in OpenAICompatProvider().stream("s", "u")]
    assert pieces == ["Hel", "lo ", "there"]


async def test_streaming_retries_without_json_mode_and_reports_errors(cloud, monkeypatch):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append("response_format" in body)
        return httpx.Response(400, json={"error": {"message": "x"}}) if "response_format" in body else httpx.Response(200, text=sse('{"a":', "1}"))

    serve(monkeypatch, handler)
    assert "".join([p async for p in OpenAICompatProvider().stream("s", "u", json_mode=True)]) == '{"a":1}'
    assert calls == [True, False]

    serve(monkeypatch, lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}))
    with pytest.raises(LLMError, match="金鑰"):
        [p async for p in OpenAICompatProvider().stream("s", "u")]


def test_the_chosen_backend_decides_the_provider_and_the_cache_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "ollama")
    assert isinstance(llm.make_provider(), llm.OllamaProvider)
    local_key = ai_cache.cache_key("word", "hello")
    monkeypatch.setattr(settings, "llm_backend", "cloud")
    monkeypatch.setattr(settings, "cloud_model", "gemini-x")
    assert isinstance(llm.make_provider(), OpenAICompatProvider)
    assert ai_cache.cache_key("word", "hello") != local_key  # another model never reuses the other's answers


# ---- speech recognition ------------------------------------------------------------------

DATA = {
    "text": "Hello there. How are you?",
    "segments": [
        {"start": 0.0, "end": 1.4, "text": " Hello there.", "avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.1},
        {"start": 1.6, "end": 3.0, "text": " How are you?", "avg_logprob": -0.3, "no_speech_prob": 0.02, "compression_ratio": 1.0},
    ],
    "words": [
        {"word": "Hello", "start": 0.0, "end": 0.5}, {"word": "there.", "start": 0.6, "end": 1.4},
        {"word": "How", "start": 1.6, "end": 1.9}, {"word": "are", "start": 1.9, "end": 2.2}, {"word": "you?", "start": 2.2, "end": 3.0},
    ],
}


def test_words_are_placed_in_their_segments():
    result = cloud_stt.to_whisper_result(DATA)
    assert [[w["word"] for w in s["words"]] for s in result["segments"]] == [["Hello", "there."], ["How", "are", "you?"]]
    assert result["segments"][0]["avg_logprob"] == -0.2  # the recogniser's own doubt is kept for the hallucination filter


def test_a_word_between_segments_goes_to_the_nearest_and_words_alone_still_work():
    data = {"segments": [{"start": 0, "end": 1, "text": "a"}, {"start": 5, "end": 6, "text": "b"}], "words": [{"word": "x", "start": 1.2, "end": 1.4}]}
    assert cloud_stt.to_whisper_result(data)["segments"][0]["words"][0]["word"] == "x"
    only_words = cloud_stt.to_whisper_result({"text": "hi", "words": [{"word": "hi", "start": 0.1, "end": 0.3}]})
    assert only_words["segments"][0]["words"][0]["word"] == "hi"


def test_the_recording_is_sent_as_a_transcription_request(cloud):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], request.content
        return httpx.Response(200, json=DATA)

    result = cloud_stt.transcribe_mp3(b"MP3DATA", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen["url"] == "https://stt.example.com/v1/audio/transcriptions" and seen["auth"] == "Bearer gsk-secret-9876"
    for part in (b"whisper-x", b"verbose_json", b"timestamp_granularities[]", b"word", b"MP3DATA", b'language'):
        assert part in seen["body"]
    assert len(result["segments"]) == 2


def test_a_busy_service_is_asked_again_after_a_pause(cloud):
    answers = [httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(503), httpx.Response(200, json=DATA)]
    pauses = []
    client = httpx.Client(transport=httpx.MockTransport(lambda request: answers.pop(0)))
    assert cloud_stt.transcribe_mp3(b"x", client=client, sleep=pauses.append)["text"].startswith("Hello")
    assert pauses[0] == 7.0 and len(pauses) == 2


def test_transcription_errors_are_readable(cloud):
    for status, expected in ((401, "金鑰"), (404, "模型"), (413, "太大")):
        client = httpx.Client(transport=httpx.MockTransport(lambda request, s=status: httpx.Response(s, json={"error": {"message": "x"}})))
        with pytest.raises(CloudSTTError, match=expected):
            cloud_stt.transcribe_mp3(b"x", client=client, sleep=lambda s: None)
    always_busy = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    with pytest.raises(CloudSTTError, match="上限"):
        cloud_stt.transcribe_mp3(b"x", client=always_busy, sleep=lambda s: None)


def test_transcribing_a_stretch_uses_the_cloud_when_chosen_and_keeps_the_times(cloud, monkeypatch):
    sent = {}
    monkeypatch.setattr(cloud_stt, "transcribe_samples", lambda samples: sent.setdefault("n", len(samples)) and cloud_stt.to_whisper_result(DATA))
    audio = np.zeros(16000 * 30, dtype=np.float32)
    words, doubtful = transcribe.transcribe_span(audio, 10.0, 20.0)
    assert sent["n"] == 16000 * 10
    assert [w.text for w in words][:2] == ["Hello", "there."] and words[0].start == pytest.approx(10.0)  # times are in the whole recording


# ---- the settings page ------------------------------------------------------------------

@pytest.fixture
def saved(client, session, monkeypatch):
    from app.db import engine as real_engine  # noqa: F401
    monkeypatch.setattr("app.routers.settings.engine", session.get_bind())
    for name in app_settings.CLOUD_FIELDS:
        monkeypatch.setattr(settings, name, getattr(settings, name))  # restored after the test
    monkeypatch.setattr(app_settings, "installed_llm_models", lambda client=None: [])
    return client


CLOUD_BODY = {"llm_backend": "cloud", "cloud_base_url": "https://api.example.com/v1", "cloud_model": "m1", "cloud_api_key": "sk-abcdef1234"}


def test_cloud_settings_are_saved_and_the_key_is_never_sent_back(saved, session):
    body = saved.put("/api/settings", json=CLOUD_BODY).json()
    assert body["llm_backend"] == "cloud" and body["cloud_model"] == "m1" and body["cloud_key"] == "••••1234"
    assert "sk-abcdef1234" not in json.dumps(body) and "sk-abcdef1234" not in json.dumps(saved.get("/api/settings").json())
    assert settings.cloud_api_key == "sk-abcdef1234" and session.get(Setting, "cloud_model").value == "m1"
    assert [p["id"] for p in body["llm_presets"]][:2] == ["gemini", "openai"] and body["stt_presets"][0]["id"] == "groq"


def test_leaving_the_key_out_keeps_it_and_an_empty_key_clears_it(saved):
    saved.put("/api/settings", json=CLOUD_BODY)
    saved.put("/api/settings", json={"cloud_model": "m2"})
    assert settings.cloud_api_key == "sk-abcdef1234" and settings.cloud_model == "m2"
    res = saved.put("/api/settings", json={"cloud_api_key": ""})  # cloud is on, so it cannot lose its key
    assert res.status_code == 400 and "金鑰" in res.json()["detail"] and settings.cloud_api_key == "sk-abcdef1234"
    assert saved.put("/api/settings", json={"llm_backend": "ollama", "cloud_api_key": ""}).json()["cloud_key"] == ""


@pytest.mark.parametrize("patch,expected", [
    ({"llm_backend": "cloud"}, "Base URL"),
    ({"llm_backend": "cloud", "cloud_base_url": "https://a.com/v1"}, "模型"),
    ({"llm_backend": "cloud", "cloud_base_url": "https://a.com/v1", "cloud_model": "m"}, "金鑰"),
    ({"cloud_base_url": "ftp://a.com"}, "http"),
    ({"llm_backend": "magic"}, "不支援"),
    ({"stt_backend": "cloud"}, "Base URL"),
])
def test_incomplete_cloud_settings_are_refused_and_nothing_changes(saved, patch, expected):
    before = settings.llm_backend
    res = saved.put("/api/settings", json=patch)
    assert res.status_code == 400 and expected in res.json()["detail"]
    assert settings.llm_backend == before


def test_a_local_server_needs_no_key(saved):
    body = saved.put("/api/settings", json={"llm_backend": "cloud", "cloud_base_url": "http://localhost:1234/v1", "cloud_model": "local"}).json()
    assert body["llm_backend"] == "cloud"


def test_saved_choices_come_back_after_a_restart(saved, session, monkeypatch):
    saved.put("/api/settings", json={**CLOUD_BODY, "stt_backend": "cloud", "stt_base_url": "https://stt.example.com/v1", "stt_model": "w", "stt_api_key": "k-1"})
    for name in app_settings.CLOUD_FIELDS:
        setattr(settings, name, "changed")
    app_settings.load_overrides(session.get_bind())
    assert settings.llm_backend == "cloud" and settings.stt_backend == "cloud" and settings.stt_api_key == "k-1"


def test_health_does_not_ask_for_ollama_when_the_cloud_does_the_work(saved, monkeypatch):
    monkeypatch.setattr(app_settings, "installed_llm_models", lambda client=None: None)  # Ollama is off
    assert saved.get("/api/health").json()["ollama"] is False
    saved.put("/api/settings", json=CLOUD_BODY)
    health = saved.get("/api/health").json()
    assert health["ollama"] is True and health["llm_model_installed"] is True and health["llm_backend"] == "cloud" and health["cloud_configured"] is True


def test_connection_tests_report_success_and_failure(saved, monkeypatch):
    async def ok():
        return {"ok": True, "message": "連線成功"}

    monkeypatch.setattr(app_settings, "check_llm", ok)
    assert saved.post("/api/settings/test/llm").json()["ok"] is True
    monkeypatch.setattr(app_settings, "check_stt", lambda: {"ok": False, "message": "拒絕了 API 金鑰"})
    assert saved.post("/api/settings/test/stt").json() == {"ok": False, "message": "拒絕了 API 金鑰"}
    assert saved.post("/api/settings/test/nothing").status_code == 404


async def test_the_llm_check_asks_the_model_and_reports_errors(cloud, monkeypatch):
    serve(monkeypatch, lambda request: reply("OK"))
    result = await app_settings.check_llm()
    assert result["ok"] is True and "tiny-model" in result["message"]
    serve(monkeypatch, lambda request: httpx.Response(401, json={}))
    result = await app_settings.check_llm()
    assert result["ok"] is False and "金鑰" in result["message"]
