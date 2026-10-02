import io
import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from app.config import settings
from app.models import Media, Recording, Segment
from app.routers.shadowing import get_feedback_provider
from app.services import shadowing
from app.services.llm import LLMError
from app.services.segmenter import Word

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def wav_bytes(seconds=2.0, amplitude=0.3, rate=16000) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    samples = (amplitude * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def said(text, prob=0.98):
    return [Word(w, i * 0.4, i * 0.4 + 0.3, prob) for i, w in enumerate(text.split())]


@pytest.fixture
def env(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    source = tmp_path / "video.wav"
    source.write_bytes(wav_bytes(seconds=5))
    media = Media(source_url="u", external_id="abcdefghijk", title="T", status="ready", audio_path=str(source))
    session.add(media)
    session.commit()
    seg = Segment(media_id=media.id, idx=0, start=1.0, end=2.0, text="Why does wasabi make your eyes water?")
    session.add(seg)
    session.commit()
    return client, session, seg, tmp_path


def upload(client, seg_id, data, name="rec.webm"):
    return client.post(f"/api/segments/{seg_id}/recordings", files={"file": (name, data, "audio/webm")})


def test_sentence_audio_is_cut_from_the_video_audio_and_cached(env, monkeypatch):
    client, _, seg, tmp = env
    calls = []
    real = shadowing.extract_clip
    monkeypatch.setattr(shadowing, "extract_clip", lambda *a: (calls.append(1), real(*a))[1])
    res = client.get(f"/api/segments/{seg.id}/audio")
    assert res.status_code == 200 and res.headers["content-type"] == "audio/wav"
    (tmp / "probe.wav").write_bytes(res.content)
    duration, _ = shadowing.wav_stats(tmp / "probe.wav")
    assert 1.2 < duration < 1.4  # one second plus 0.15 s of room on each side
    client.get(f"/api/segments/{seg.id}/audio")
    assert len(calls) == 1


def test_sentence_audio_reports_missing_source_or_segment(env, session):
    client, _, seg, _ = env
    assert client.get("/api/segments/9999/audio").status_code == 404
    Path(session.get(Media, seg.media_id).audio_path).unlink()
    assert client.get(f"/api/segments/{seg.id}/audio").status_code == 404


def test_upload_compares_the_recording_and_keeps_a_history(env, monkeypatch):
    client, _, seg, tmp = env
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: said("Why does wasabi make eyes water"))
    res = upload(client, seg.id, wav_bytes())
    assert res.status_code == 200
    body = res.json()
    assert body["score"] == 86 and body["heard_text"] == "Why does wasabi make eyes water"
    assert [t["status"] for t in body["tokens"]].count("missing") == 1
    assert {"text": "your", "status": "missing", "heard": None} in body["tokens"]
    assert 1.9 < body["duration"] < 2.1 and body["feedback"] is None
    # stored as a 16 kHz wav, and playable through the API; the raw upload is not left behind
    assert client.get(f"/api/recordings/{body['id']}/audio").status_code == 200
    assert not list((tmp / "recordings").rglob("*.upload"))
    # second attempt shows up first in the history
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: said("Why does wasabi make your eyes water"))
    upload(client, seg.id, wav_bytes())
    history = client.get(f"/api/segments/{seg.id}/recordings").json()
    assert [h["score"] for h in history] == [100, 86]


def test_upload_rejects_silence_garbage_and_empty_files(env, monkeypatch):
    client, _, seg, tmp = env
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: pytest.fail("should not be reached"))
    assert upload(client, seg.id, wav_bytes(amplitude=0.0)).status_code == 422
    assert upload(client, seg.id, b"this is not audio at all").status_code == 400
    assert upload(client, seg.id, b"").status_code == 400
    assert client.post("/api/segments/9999/recordings", files={"file": ("a.wav", wav_bytes(), "audio/wav")}).status_code == 404
    assert not [p for p in (tmp / "recordings").rglob("*") if p.is_file()]  # failed uploads leave nothing behind


def test_upload_says_so_when_speech_recognition_is_busy(env, monkeypatch):
    client, _, seg, tmp = env

    def busy(wav):
        raise shadowing.TranscriberBusy("語音辨識正在處理影片，請稍後再試")

    monkeypatch.setattr(shadowing, "transcribe_recording", busy)
    res = upload(client, seg.id, wav_bytes())
    assert res.status_code == 503 and "稍後" in res.json()["detail"]
    assert not [p for p in (tmp / "recordings").rglob("*") if p.is_file()]


def test_a_recording_that_recognises_nothing_scores_zero(env, monkeypatch):
    client, _, seg, _ = env
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: [])
    body = upload(client, seg.id, wav_bytes()).json()
    assert body["score"] == 0 and all(t["status"] == "missing" for t in body["tokens"])


def test_delete_removes_the_row_and_the_file(env, monkeypatch):
    client, session, seg, _ = env
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: said("Why"))
    rec = upload(client, seg.id, wav_bytes()).json()
    path = Path(session.get(Recording, rec["id"]).file_path)
    assert path.exists()
    assert client.delete(f"/api/recordings/{rec['id']}").status_code == 200
    assert not path.exists() and client.get(f"/api/recordings/{rec['id']}/audio").status_code == 404
    assert client.delete(f"/api/recordings/{rec['id']}").status_code == 404


class FakeCoach:
    calls = 0
    fail = False
    prompts: list[str] = []

    async def stream(self, system, user, *, json_mode=False):
        FakeCoach.calls += 1
        FakeCoach.prompts.append(user)
        if FakeCoach.fail:
            raise LLMError("boom")
        text = json.dumps({"summary": "很好，只漏了 your。", "tips": ["your 是弱讀，要輕輕帶過"]}, ensure_ascii=False)
        for i in range(0, len(text), 12):
            yield text[i : i + 12]

    async def chat(self, *a, **k):
        raise AssertionError


def events(res):
    return [json.loads(line) for line in res.text.splitlines() if line]


def test_feedback_streams_uses_the_comparison_facts_and_is_saved(env, monkeypatch):
    from app.main import app

    client, _, seg, _ = env
    FakeCoach.calls, FakeCoach.fail, FakeCoach.prompts = 0, False, []
    app.dependency_overrides[get_feedback_provider] = lambda: FakeCoach()
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: said("Why does wasabi make eyes water", prob=0.98))
    rec = upload(client, seg.id, wav_bytes()).json()

    got = events(client.post(f"/api/recordings/{rec['id']}/feedback/stream"))
    assert got[-1]["type"] == "done" and got[-1]["data"]["tips"] == ["your 是弱讀，要輕輕帶過"]
    assert any(e["type"] == "partial" for e in got[:-1])
    prompt = FakeCoach.prompts[0]
    assert "原句：Why does wasabi make your eyes water?" in prompt and "漏掉的字：your" in prompt and "完整度：86%" in prompt
    # saved: shows in the history, and asking again does not call the model again
    assert client.get(f"/api/segments/{seg.id}/recordings").json()[0]["feedback"]["summary"].startswith("很好")
    again = events(client.post(f"/api/recordings/{rec['id']}/feedback/stream"))
    assert [e["type"] for e in again] == ["done"] and FakeCoach.calls == 1


def test_feedback_reports_model_errors_and_does_not_save_them(env, monkeypatch):
    from app.main import app

    client, _, seg, _ = env
    FakeCoach.calls, FakeCoach.fail, FakeCoach.prompts = 0, True, []
    app.dependency_overrides[get_feedback_provider] = lambda: FakeCoach()
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: said("Why"))
    rec = upload(client, seg.id, wav_bytes()).json()
    assert events(client.post(f"/api/recordings/{rec['id']}/feedback/stream"))[-1] == {"type": "error", "message": "boom"}
    assert client.get(f"/api/segments/{seg.id}/recordings").json()[0]["feedback"] is None
    assert client.post("/api/recordings/9999/feedback/stream").status_code == 404


def test_feedback_that_claims_phonetic_detail_is_cleaned_before_it_is_sent_and_saved(env, monkeypatch):
    from app.main import app

    class Chatty(FakeCoach):
        async def stream(self, system, user, *, json_mode=False):
            text = json.dumps({"summary": "不錯。eyes 的 /aɪ/ 要清楚。", "tips": ["注意 /ɜːr/ 音", "放慢速度重念"]}, ensure_ascii=False)
            for i in range(0, len(text), 10):
                yield text[i : i + 10]

    client, _, seg, _ = env
    app.dependency_overrides[get_feedback_provider] = lambda: Chatty()
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: said("Why does wasabi make your ears water"))
    rec = upload(client, seg.id, wav_bytes()).json()
    got = events(client.post(f"/api/recordings/{rec['id']}/feedback/stream"))
    assert got[-1]["data"] == {"summary": "不錯。", "tips": ["放慢速度重念"]}
    for e in got:  # not even a partial update showed the made-up detail once it had been written
        assert "ɪ" not in json.dumps(e, ensure_ascii=False) and "ɜ" not in json.dumps(e, ensure_ascii=False)
    assert client.get(f"/api/segments/{seg.id}/recordings").json()[0]["feedback"]["tips"] == ["放慢速度重念"]
