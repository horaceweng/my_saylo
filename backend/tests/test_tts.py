import os
import time

import numpy as np
import pytest

from app.config import settings
from app.services import tts
from app.services.tts import TTSError


@pytest.fixture
def env(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(tts, "_pruned", True)
    made = []

    def fake_synthesize(text, voice):
        made.append((text, voice.id))
        return np.zeros(2400)

    monkeypatch.setattr(tts, "synthesize", fake_synthesize)
    monkeypatch.setattr(tts, "to_mp3", lambda samples: b"MP3:" + str(len(samples)).encode())
    monkeypatch.setattr(tts, "problems", lambda: [])
    return client, tmp_path, made


def test_speaking_makes_the_audio_once_and_reuses_it(env):
    client, _, made = env
    first = client.post("/api/tts/speak", json={"text": "Hello   there.", "voice": "bf_emma"})
    assert first.status_code == 200 and first.headers["content-type"] == "audio/mpeg" and first.content == b"MP3:2400"
    second = client.post("/api/tts/speak", json={"text": "Hello there.", "voice": "bf_emma"})  # spaces do not matter
    assert second.content == first.content and made == [("Hello there.", "bf_emma")]
    client.post("/api/tts/speak", json={"text": "Hello there.", "voice": "af_heart"})  # another voice is another recording
    assert len(made) == 2


def test_bad_requests_are_refused_with_a_reason(env):
    client, _, made = env
    assert client.post("/api/tts/speak", json={"text": "   "}).status_code == 400
    assert client.post("/api/tts/speak", json={"text": "* * *"}).status_code == 400  # nothing to say
    assert client.post("/api/tts/speak", json={"text": "x" * 601}).status_code == 400
    res = client.post("/api/tts/speak", json={"text": "Hi.", "voice": "nobody"})
    assert res.status_code == 400 and "聲音" in res.json()["detail"]
    assert made == []


def test_when_the_voice_cannot_run_the_reason_is_reported(env, monkeypatch):
    client, _, made = env
    monkeypatch.setattr(tts, "problems", lambda: ["找不到 espeak-ng：請執行 brew install espeak-ng"])
    res = client.post("/api/tts/speak", json={"text": "Hi there."})
    assert res.status_code == 400 and "espeak-ng" in res.json()["detail"] and made == []
    status = client.get("/api/tts/status").json()
    assert status["available"] is False and "espeak-ng" in status["problems"][0]


def test_something_already_recorded_can_be_played_even_if_the_voice_is_unavailable(env, monkeypatch):
    client, _, made = env
    client.post("/api/tts/speak", json={"text": "Once made."})
    monkeypatch.setattr(tts, "problems", lambda: ["broken"])
    assert client.post("/api/tts/speak", json={"text": "Once made."}).status_code == 200


def test_status_lists_the_voices(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(tts, "model_downloaded", lambda: True)
    status = client.get("/api/tts/status").json()
    assert status["available"] is True and status["model_downloaded"] is True
    assert status["default_voice"] in [v["id"] for v in status["voices"]]


def test_audio_not_played_for_a_month_is_deleted(env):
    _, tmp_path, _ = env
    old, fresh = tts.cache_path("old text", "af_heart"), tts.cache_path("fresh text", "af_heart")
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x"); fresh.write_bytes(b"x")
    long_ago = time.time() - 40 * 86400
    os.utime(old, (long_ago, long_ago))
    assert tts.prune_cache() == 1
    assert not old.exists() and fresh.exists()


def test_playing_again_keeps_it_from_being_deleted(env):
    _, tmp_path, made = env
    path = tts.speak_file("Keep me.", "af_heart")
    long_ago = time.time() - 40 * 86400
    os.utime(path, (long_ago, long_ago))
    tts.speak_file("Keep me.", "af_heart")  # played again
    assert tts.prune_cache() == 0 and path.exists() and len(made) == 1


def test_every_voice_is_english_and_british_ones_use_the_british_model():
    assert all(v.id[0] in "ab" for v in tts.VOICES)
    assert {v.id: v.lang_code for v in tts.VOICES}["bf_emma"] == "b"
    assert {v.id: v.lang_code for v in tts.VOICES}["af_heart"] == "a"


def test_generation_errors_surface_as_readable_messages(env, monkeypatch):
    client, *_ = env

    def fail(text, voice):
        raise TTSError("這段文字念不出來")

    monkeypatch.setattr(tts, "synthesize", fail)
    res = client.post("/api/tts/speak", json={"text": "Hm."})
    assert res.status_code == 400 and "念不出來" in res.json()["detail"]
