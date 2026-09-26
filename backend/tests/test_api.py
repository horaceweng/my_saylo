import json

from app.config import settings
from app.models import Media, Segment, Word
import pytest

needs_dict = pytest.mark.skipif(not settings.dict_db_path.exists(), reason="dict.sqlite not built")


def test_phrases_crud_and_dedupe(client):
    body = {"text": "break the ice", "context_sentence": "Let's break the ice.", "source_id": 1, "timestamp": 12.5}
    first = client.post("/api/phrases", json=body).json()
    again = client.post("/api/phrases", json=body).json()
    assert first["id"] == again["id"]
    assert len(client.get("/api/phrases").json()) == 1
    assert len(client.get("/api/phrases", params={"q": "ice"}).json()) == 1
    assert client.get("/api/phrases", params={"q": "zzz"}).json() == []
    assert client.delete(f"/api/phrases/{first['id']}").status_code == 200
    assert client.delete(f"/api/phrases/{first['id']}").status_code == 404


def test_rejects_non_youtube_url(client):
    assert client.post("/api/media", json={"url": "https://example.com/x"}).status_code == 400


def test_media_detail_nests_segments_and_words(client, session):
    m = Media(source_url="u", external_id="abcdefghijk", title="T", status="ready")
    session.add(m)
    session.commit()
    seg = Segment(media_id=m.id, idx=0, start=0, end=1, text="Hi there.", translation="嗨")
    session.add(seg)
    session.commit()
    session.add(Word(segment_id=seg.id, idx=0, text="Hi", start=0, end=0.4))
    session.add(Word(segment_id=seg.id, idx=1, text="there.", start=0.4, end=1))
    session.commit()
    data = client.get(f"/api/media/{m.id}").json()
    assert data["segments"][0]["translation"] == "嗨"
    assert [w["text"] for w in data["segments"][0]["words"]] == ["Hi", "there."]
    assert client.delete(f"/api/media/{m.id}").status_code == 200
    assert client.get(f"/api/media/{m.id}").status_code == 404


def test_explain_sentence_is_cached(client, fake_llm):
    fake_llm.replies["英文老師"] = json.dumps({"translation": "越多越好", "structure": "The + 比較級", "similar_examples": [{"en": "a", "zh": "b"}]})
    body = {"sentence": "The more, the better."}
    a = client.post("/api/ai/explain-sentence", json=body).json()
    b = client.post("/api/ai/explain-sentence", json=body).json()
    assert a == b and a["structure"] == "The + 比較級"
    assert fake_llm.calls == 1


class FakeWordCoach:
    calls = 0
    fail = False

    async def stream(self, system, user, *, json_mode=False):
        FakeWordCoach.calls += 1
        if FakeWordCoach.fail:
            from app.services.llm import LLMError

            raise LLMError("無法連線到 Ollama，請確認已執行 `ollama serve`")
        text = json.dumps({"english_definition": "to move", "synonyms": ["proceed"], "root": {"part": "go", "meaning": "走"}})
        for i in range(0, len(text), 15):
            yield text[i : i + 15]


def _word_events(res):
    return [json.loads(line) for line in res.text.splitlines() if line]


@needs_dict
def test_a_word_comes_back_at_once_and_the_ai_part_is_streamed_and_kept(client):
    from app.main import app
    from app.routers.dictionary import get_word_provider

    FakeWordCoach.calls, FakeWordCoach.fail = 0, False
    app.dependency_overrides[get_word_provider] = lambda: FakeWordCoach()
    first = client.get("/api/dictionary/went").json()
    assert first["found"] and first["entry"]["word"] == "go" and first["entry"]["is_inflection"] is True
    assert first["ai"] is None and FakeWordCoach.calls == 0  # looking a word up never waits for the model

    got = _word_events(client.post("/api/dictionary/went/enrich/stream"))
    assert got[-1]["type"] == "done" and got[-1]["data"]["synonyms"] == ["proceed"]
    assert any(e["type"] == "partial" for e in got[:-1]) and got[0]["type"] == "partial"
    assert client.get("/api/dictionary/went").json()["ai"]["english_definition"] == "to move"  # kept
    again = _word_events(client.post("/api/dictionary/went/enrich/stream"))
    assert [e["type"] for e in again] == ["done"] and FakeWordCoach.calls == 1  # not asked twice


@needs_dict
def test_the_dictionary_part_works_when_ollama_is_down_and_the_stream_says_so(client):
    from app.main import app
    from app.routers.dictionary import get_word_provider

    FakeWordCoach.calls, FakeWordCoach.fail = 0, True
    app.dependency_overrides[get_word_provider] = lambda: FakeWordCoach()
    data = client.get("/api/dictionary/apple").json()
    assert data["found"] and "蘋果" in data["entry"]["translation"] and data["ai"] is None
    got = _word_events(client.post("/api/dictionary/apple/enrich/stream"))
    assert got[-1]["type"] == "error" and "Ollama" in got[-1]["message"]
    assert client.get("/api/dictionary/apple").json()["ai"] is None  # a failure is not remembered


def test_enrich_rejects_things_that_are_not_words(client):
    assert client.post("/api/dictionary/123/enrich/stream").status_code == 400


@needs_dict
def test_root_words_drops_invented_words(client, fake_llm):
    fake_llm.replies["詞源學"] = json.dumps({"words": ["portable", "transport", "zzzfakeword", "import", "specify"]})
    words = [w["word"] for w in client.get("/api/dictionary/root/port").json()["words"]]
    assert "portable" in words and "transport" in words
    assert "zzzfakeword" not in words  # not in the dictionary
    assert "specify" not in words  # real word, but does not contain the root "port"


def test_invalid_word_rejected(client):
    assert client.get("/api/dictionary/123").status_code == 400


def test_retry_returns_the_media_row(client, session, monkeypatch):
    monkeypatch.setattr("app.routers.media.pipeline.enqueue", lambda media_id: None)
    m = Media(source_url="u", external_id="abcdefghijk", title="T", status="error", error="boom")
    session.add(m)
    session.commit()
    data = client.post(f"/api/media/{m.id}/retry").json()
    assert data["id"] == m.id and data["status"] == "pending" and data["error"] == ""


@needs_dict
def test_root_missing_silent_e_is_restored(client, fake_llm):
    fake_llm.replies["詞源學"] = json.dumps({"words": ["spicy", "spiced", "spice", "specify"]})
    data = client.get("/api/dictionary/root/spic").json()
    assert data["root"] == "spice"
    words = [w["word"] for w in data["words"]]
    assert "spicy" in words and "specify" not in words


def _explain_service_override():
    from sqlmodel import SQLModel, create_engine
    from sqlmodel.pool import StaticPool

    from app.main import app
    from app.routers.ai import get_explain_service
    from app.services.explain_queue import ExplainService
    from tests.test_explain_queue import FakeProvider

    FakeProvider.log, FakeProvider.gates, FakeProvider.fail, FakeProvider.bad_json = [], {}, set(), set()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    service = ExplainService(engine, provider_factory=FakeProvider, throttle=0)
    app.dependency_overrides[get_explain_service] = lambda: service
    return service, FakeProvider


def test_explain_stream_endpoint_sends_ndjson_partials_then_done(client):
    _, provider = _explain_service_override()
    res = client.post("/api/ai/explain-sentence/stream", json={"sentence": "Hello there."})
    assert res.status_code == 200 and res.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in res.text.splitlines() if line]
    assert events[-1]["type"] == "done" and events[-1]["data"]["translation"] == "譯:Hello there."
    assert any(e["type"] == "partial" for e in events[:-1])
    # the second call is answered from the cache with a single event
    provider.log.clear()
    again = [json.loads(line) for line in client.post("/api/ai/explain-sentence/stream", json={"sentence": "Hello there."}).text.splitlines()]
    assert [e["type"] for e in again] == ["done"] and provider.log == []


def test_explain_stream_reports_model_errors_in_band(client):
    _, provider = _explain_service_override()
    provider.fail.add("Boom.")
    events = [json.loads(line) for line in client.post("/api/ai/explain-sentence/stream", json={"sentence": "Boom."}).text.splitlines()]
    assert events[-1] == {"type": "error", "message": "boom"}


def test_prefetch_endpoint_no_longer_exists(client):
    assert client.post("/api/ai/explain-sentence/prefetch", json={"items": [{"sentence": "A"}]}).status_code == 404


def _media_with_segments(session, translated):
    m = Media(source_url="u", external_id="abcdefghijk", title="T", status="error", error="x", audio_path="a.m4a")
    session.add(m)
    session.commit()
    for i, tr in enumerate(translated):
        seg = Segment(media_id=m.id, idx=i, start=i, end=i + 1, text=f"s{i}", translation=tr)
        session.add(seg)
        session.commit()
        session.add(Word(segment_id=seg.id, idx=0, text=f"s{i}", start=i, end=i + 1))
    session.commit()
    return m


def test_retry_keeps_finished_work_but_restart_throws_it_away(client, session, monkeypatch):
    queued = []
    monkeypatch.setattr("app.routers.media.pipeline.enqueue", queued.append)
    m = _media_with_segments(session, ["甲", "乙", ""])
    client.post(f"/api/media/{m.id}/retry")
    assert len(client.get(f"/api/media/{m.id}").json()["segments"]) == 3 and queued == [m.id]
    client.post(f"/api/media/{m.id}/retry", params={"restart": "true"})
    assert client.get(f"/api/media/{m.id}").json()["segments"] == [] and queued == [m.id, m.id]


# ---- progress information for the page --------------------------------------------------------


def _add_sentences(session, media, translations):
    for i, tr in enumerate(translations):
        seg = Segment(media_id=media.id, idx=i, start=i * 5.0, end=i * 5.0 + 4, text=f"sentence {i}", translation=tr)
        session.add(seg)
        session.commit()
        session.add(Word(segment_id=seg.id, idx=0, text=f"w{i}", start=i * 5.0, end=i * 5.0 + 1))
    session.commit()


def test_media_reports_what_is_ready_and_becomes_playable_after_enough_translations(client, session, monkeypatch):
    monkeypatch.setattr("app.routers.media.pipeline.PLAYABLE_AFTER", 3)
    m = Media(source_url="u", external_id="abcdefghijk", title="T", status="transcribing", duration=120)
    session.add(m)
    session.commit()
    row = client.get("/api/media").json()[0]
    assert (row["sentence_count"], row["translated_count"], row["covered_until"], row["playable"]) == (0, 0, 0.0, False)
    _add_sentences(session, m, ["甲", "乙", "", ""])
    row = client.get("/api/media").json()[0]
    assert (row["sentence_count"], row["translated_count"], row["covered_until"], row["playable"]) == (4, 2, 19.0, False)
    _add_sentences_more = Segment(media_id=m.id, idx=4, start=20, end=24, text="s4", translation="丙")
    session.add(_add_sentences_more)
    session.commit()
    detail = client.get(f"/api/media/{m.id}").json()
    assert detail["translated_count"] == 3 and detail["playable"] is True and detail["status"] == "transcribing"
    assert len(detail["segments"]) == 5


def test_a_finished_media_is_playable_even_when_short(client, session):
    m = Media(source_url="u", external_id="abcdefghijk", title="T", status="ready")
    session.add(m)
    session.commit()
    _add_sentences(session, m, ["甲"])
    assert client.get(f"/api/media/{m.id}").json()["playable"] is True


def test_updates_send_only_new_sentences_and_translations_that_arrived(client, session):
    m = Media(source_url="u", external_id="abcdefghijk", title="T", status="translating", progress=60)
    session.add(m)
    session.commit()
    _add_sentences(session, m, ["甲", "", "丙", "", ""])
    # the page knows sentences 0-2 but has no translation for #1 yet
    body = client.get(f"/api/media/{m.id}/updates", params={"known": 3, "missing_from": 1}).json()
    assert body["translations"] == {"2": "丙"}  # index 0 is before missing_from; #1 is still empty
    assert [s["idx"] for s in body["new_segments"]] == [3, 4] and body["new_segments"][0]["words"][0]["text"] == "w3"
    assert body["status"] == "translating" and body["progress"] == 60 and body["sentence_count"] == 5
    up_to_date = client.get(f"/api/media/{m.id}/updates", params={"known": 5, "missing_from": 5}).json()
    assert up_to_date["new_segments"] == [] and up_to_date["translations"] == {}
    assert client.get("/api/media/9999/updates").status_code == 404


def test_focus_is_passed_to_the_translator(client, monkeypatch):
    seen = []
    monkeypatch.setattr("app.routers.media.pipeline.set_focus", lambda media_id, idx: seen.append((media_id, idx)))
    assert client.post("/api/media/7/focus", json={"idx": 42}).json() == {"ok": True}
    assert seen == [(7, 42)]
    assert client.post("/api/media/7/focus", json={}).status_code == 422


def test_restart_also_clears_the_transcribed_flag(client, session, monkeypatch):
    monkeypatch.setattr("app.routers.media.pipeline.enqueue", lambda media_id: None)
    m = Media(source_url="u", external_id="abcdefghijk", title="T", status="ready", transcribed=True)
    session.add(m)
    session.commit()
    client.post(f"/api/media/{m.id}/retry")
    assert session.get(Media, m.id).transcribed is True  # a plain retry continues
    client.post(f"/api/media/{m.id}/retry", params={"restart": "true"})
    session.expire_all()
    assert session.get(Media, m.id).transcribed is False
