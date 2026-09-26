import threading
import time

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models import Media, Segment
from app.models import Word as DbWord
from app.services import pipeline
from app.services.pipeline import translate_sentences
from app.services.segmenter import Word


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.users = []

    async def chat(self, system, user, *, json_mode=False):
        self.users.append(user)
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_batch_ok():
    p = Scripted(['{"translations": {"1": "甲", "2": "乙"}}'])
    assert await translate_sentences(["a", "b"], p) == ["甲", "乙"]


@pytest.mark.asyncio
async def test_skipped_sentence_is_retried_alone():
    p = Scripted(['{"translations": {"1": "甲", "3": "丙"}}', '{"translations": {"1": "乙"}}'])
    assert await translate_sentences(["a", "b", "c"], p) == ["甲", "乙", "丙"]
    assert p.users[1] == "1. b"


@pytest.mark.asyncio
async def test_unrecoverable_sentence_becomes_empty_string():
    p = Scripted(['{"translations": {"1": "甲"}}', "garbage", "garbage"])
    assert await translate_sentences(["a", "b"], p) == ["甲", ""]


# ---- the resumable, piece-by-piece job ---------------------------------------------------------


def speech(n_sentences, sentence_seconds=4.0, gap=0.5, words_per_sentence=4):
    words, t = [], 0.0
    for i in range(n_sentences):
        step = sentence_seconds / words_per_sentence
        for j in range(words_per_sentence):
            text = f"s{i}w{j}" + ("." if j == words_per_sentence - 1 else "")
            words.append(Word(text, t + j * step, t + (j + 1) * step - 0.05))
        t += sentence_seconds + gap
    return words


@pytest.fixture
def job(monkeypatch):
    """A pipeline wired to an in-memory database, a fake 60 s recording (13 sentences) and fakes for the slow parts."""
    import functools

    import numpy as np

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(pipeline, "engine", engine)
    words = speech(13)
    events: list[str] = []
    calls = {"download": 0, "spans": [], "translated": [], "doubtful": False}

    def download(video_id):
        calls["download"] += 1
        return f"/audio/{video_id}.m4a"

    def span(audio, t0, t1):
        calls["spans"].append((round(t0, 1), round(t1, 1)))
        events.append("transcribe")
        got = [w for w in words if w.start >= t0 - 1e-9 and w.end <= t1 + 1e-9]
        return ([], got) if calls["doubtful"] else (got, [])

    async def translate(texts, provider=None):
        calls["translated"].append(list(texts))
        events.append("translate")
        return [f"譯:{t}" for t in texts]

    monkeypatch.setattr(pipeline.youtube, "download_audio", download)
    monkeypatch.setattr(pipeline, "load_audio", lambda path: np.zeros(60 * pipeline.SAMPLE_RATE))
    monkeypatch.setattr(pipeline, "transcribe_span", span)
    monkeypatch.setattr(pipeline, "transcribe_in_pieces", functools.partial(pipeline.transcribe_in_pieces, chunk=20, overlap=6))
    monkeypatch.setattr(pipeline, "translate_sentences", translate)
    monkeypatch.setattr(pipeline, "BATCH_SIZE", 2)
    monkeypatch.setattr(pipeline, "PLAYABLE_AFTER", 4)
    monkeypatch.setattr(pipeline, "LOOKAHEAD", 4)
    calls["events"] = events
    return engine, calls


def add_media(engine, audio_path="", status="pending", transcribed=False, kind="video", source_url="u", duration=0.0):
    with Session(engine) as s:
        m = Media(kind=kind, source_url=source_url, external_id="abcdefghijk", title="T", status=status, audio_path=audio_path, transcribed=transcribed, duration=duration)
        s.add(m)
        s.commit()
        s.refresh(m)
        return m.id


def add_segments(engine, media_id, translations, first_idx=0):
    with Session(engine) as s:
        for k, tr in enumerate(translations):
            i = first_idx + k
            seg = Segment(media_id=media_id, idx=i, start=i * 4.5, end=i * 4.5 + 4, text=f"s{i}w0 s{i}w1 s{i}w2 s{i}w3.", translation=tr)
            s.add(seg)
            s.commit()
            s.add(DbWord(segment_id=seg.id, idx=0, text="x", start=i, end=i + 1))
        s.commit()


def state(engine, media_id):
    with Session(engine) as s:
        m = s.get(Media, media_id)
        segs = s.exec(select(Segment).where(Segment.media_id == media_id).order_by(Segment.idx)).all()
        return m, segs


def test_a_fresh_job_transcribes_in_pieces_and_ends_with_every_sentence_translated_once(job):
    engine, calls = job
    mid = add_media(engine)
    pipeline.process_media(mid)
    media, segs = state(engine, mid)
    assert media.status == "ready" and media.progress == 100 and media.transcribed and media.audio_path.endswith(".m4a")
    assert calls["download"] == 1 and len(calls["spans"]) > 2  # several pieces, not one long transcription
    assert [s.text for s in segs] == [f"s{i}w0 s{i}w1 s{i}w2 s{i}w3." for i in range(13)]  # none lost, cut or repeated
    assert [s.idx for s in segs] == list(range(13))
    assert all(s.translation == f"譯:{s.text}" for s in segs)
    assert sorted(t for batch in calls["translated"] for t in batch) == sorted(s.text for s in segs)  # each translated once


def test_the_first_sentences_are_translated_before_the_rest_is_even_transcribed(job):
    engine, calls = job
    pipeline.process_media(add_media(engine))
    events = calls["events"]
    second_transcribe = [i for i, e in enumerate(events) if e == "transcribe"][1]
    translated_before = sum(len(b) for b in calls["translated"][: events[:second_transcribe].count("translate")])
    assert translated_before == 4  # LOOKAHEAD sentences: the video can be opened here


def test_while_transcribing_only_the_sentences_after_the_learner_are_translated(job):
    engine, calls = job
    mid = add_media(engine)
    pipeline.set_focus(mid, 7)  # the learner is already at sentence 7, which the first pieces do not reach
    pipeline.process_media(mid)
    events = calls["events"]
    first_translate = events.index("translate")
    assert events[:first_translate].count("transcribe") >= 2  # nothing worth translating existed after piece 1
    first_batch = calls["translated"][0]
    assert first_batch[0].startswith("s7w0")  # it began at the learner, not at sentence 0
    media, segs = state(engine, mid)
    assert media.status == "ready" and all(s.translation for s in segs)  # and finished everything else afterwards


def test_a_job_cut_off_while_transcribing_continues_after_the_last_saved_sentence(job):
    engine, calls = job
    mid = add_media(engine, audio_path="/audio/x.m4a", status="transcribing")
    add_segments(engine, mid, ["譯:a", "譯:b", "譯:c"])  # three sentences were saved before the restart
    pipeline.process_media(mid)
    media, segs = state(engine, mid)
    assert calls["download"] == 0  # the audio is already there
    assert calls["spans"][0][0] == pytest.approx(2 * 4.5 + 4)  # starts right after the last saved sentence
    assert media.status == "ready" and media.transcribed
    assert [s.idx for s in segs] == list(range(len(segs))) and len({s.text for s in segs}) == len(segs)
    assert [s.translation for s in segs[:3]] == ["譯:a", "譯:b", "譯:c"]  # earlier work untouched


def test_a_job_cut_off_while_translating_only_translates_what_is_missing(job):
    engine, calls = job
    mid = add_media(engine, audio_path="/audio/x.m4a", status="translating", transcribed=True)
    add_segments(engine, mid, ["甲", "乙", "丙", "", ""])
    pipeline.process_media(mid)
    media, segs = state(engine, mid)
    assert media.status == "ready" and calls["spans"] == [] and calls["download"] == 0
    assert sorted(t for b in calls["translated"] for t in b) == ["s3w0 s3w1 s3w2 s3w3.", "s4w0 s4w1 s4w2 s4w3."]
    assert [s.translation for s in segs][:3] == ["甲", "乙", "丙"]


def test_translation_starts_where_the_learner_is_and_then_wraps_around(job):
    engine, calls = job
    mid = add_media(engine, audio_path="/audio/x.m4a", status="translating", transcribed=True)
    add_segments(engine, mid, [""] * 8)
    pipeline.set_focus(mid, 5)
    pipeline.process_media(mid)
    order = [int(t.split()[0][1:-2]) for batch in calls["translated"] for t in batch]
    assert order == [5, 6, 7, 0, 1, 2, 3, 4]
    assert mid not in pipeline._focus  # forgotten once the video is done


def test_a_sentence_that_cannot_be_translated_is_not_retried_forever(job, monkeypatch):
    engine, calls = job

    async def flaky(texts, provider=None):
        calls["translated"].append(list(texts))
        return ["" if "s1w0" in t else f"譯:{t}" for t in texts]

    monkeypatch.setattr(pipeline, "translate_sentences", flaky)
    mid = add_media(engine, audio_path="/audio/x.m4a", status="translating", transcribed=True)
    add_segments(engine, mid, [""] * 4)
    pipeline.process_media(mid)
    media, segs = state(engine, mid)
    assert media.status == "ready" and [s.translation for s in segs][1] == ""
    assert sum(1 for b in calls["translated"] for t in b if "s1w0" in t) == 1


def test_if_nothing_anywhere_looks_reliable_the_doubtful_text_is_shown_rather_than_erased(job):
    engine, calls = job
    calls["doubtful"] = True
    mid = add_media(engine)
    pipeline.process_media(mid)
    media, segs = state(engine, mid)
    assert media.status == "ready"
    # Last resort: the pieces are joined as they are, so a sentence may be split where two pieces meet and a
    # word straddling that point can be lost (3 pieces, 2 joins). Normal transcription does not have this.
    words = sum(len(x.text.split()) for x in segs)
    assert 13 * 4 - 2 <= words <= 13 * 4


def test_deleting_the_video_while_it_is_processed_stops_the_job_without_leftovers(job, monkeypatch):
    engine, calls = job
    mid = add_media(engine)
    real_span = pipeline.transcribe_span

    def span_then_delete(audio, t0, t1):
        out = real_span(audio, t0, t1)
        if len(calls["spans"]) == 2:  # the learner presses delete while the second piece is being made
            with Session(engine) as s:
                s.delete(s.get(Media, mid))
                s.commit()
        return out

    monkeypatch.setattr(pipeline, "transcribe_span", span_then_delete)
    pipeline.process_media(mid)  # must not raise
    with Session(engine) as s:
        assert s.get(Media, mid) is None
        assert len(s.exec(select(Segment).where(Segment.media_id == mid)).all()) <= 4 * 3  # nothing added after the delete


def test_a_podcast_is_downloaded_from_its_link_not_from_youtube_and_its_real_length_is_stored(job, monkeypatch, tmp_path):
    engine, calls = job
    downloads = []

    def fetch(url, dest_dir, progress=None, client=None):
        downloads.append(url)
        progress and progress(0.5)
        return tmp_path / "podcast_x.mp3"

    monkeypatch.setattr(pipeline.podcast, "download_audio", fetch)
    monkeypatch.setattr(pipeline.youtube, "download_audio", lambda vid: pytest.fail("a podcast must not go through YouTube"))
    mid = add_media(engine, kind="podcast", source_url="https://media.example.com/ep.mp3", duration=372.0)
    pipeline.process_media(mid)
    media, segs = state(engine, mid)
    assert downloads == ["https://media.example.com/ep.mp3"]
    assert media.status == "ready" and media.audio_path.endswith("podcast_x.mp3") and len(segs) == 13
    assert media.duration == 60.0  # the recording is 60 s; the feed's figure (372) was wrong


def test_an_uploaded_file_is_not_downloaded_at_all(job, monkeypatch):
    engine, calls = job
    monkeypatch.setattr(pipeline.podcast, "download_audio", lambda *a, **k: pytest.fail("nothing to download"))
    mid = add_media(engine, kind="podcast", source_url="upload:talk.mp3", audio_path="/data/audio/upload_1.mp3")
    pipeline.process_media(mid)
    assert state(engine, mid)[0].status == "ready" and calls["download"] == 0


def test_a_failed_podcast_download_is_reported_with_the_reason(job, monkeypatch):
    engine, _ = job

    def fail(*a, **k):
        raise pipeline.podcast.PodcastError("下載失敗（HTTP 403）")

    monkeypatch.setattr(pipeline.podcast, "download_audio", fail)
    mid = add_media(engine, kind="podcast", source_url="https://a.com/ep.mp3")
    pipeline.process_media(mid)
    media, _ = state(engine, mid)
    assert media.status == "error" and "HTTP 403" in media.error


def test_a_failure_is_reported_on_the_media_row(job, monkeypatch):
    engine, _ = job
    monkeypatch.setattr(pipeline, "transcribe_span", lambda audio, a, b: ([], []))
    mid = add_media(engine)
    pipeline.process_media(mid)
    media, _ = state(engine, mid)
    assert media.status == "error" and "沒有辨識到" in media.error


def test_finished_jobs_are_not_touched_on_startup(job, monkeypatch):
    engine, _ = job
    queued = []
    monkeypatch.setattr(pipeline, "enqueue", queued.append)
    ids = {s: add_media(engine, status=s) for s in ["pending", "downloading", "transcribing", "translating", "ready", "error"]}
    assert set(pipeline.resume_unfinished()) == {ids[s] for s in ["pending", "downloading", "transcribing", "translating"]}
    assert set(queued) == set(pipeline.resume_unfinished())


def test_the_worker_is_a_daemon_and_never_runs_the_same_media_twice_at_once(monkeypatch):
    started, release, runs = threading.Event(), threading.Event(), []

    def slow(media_id):
        runs.append(media_id)
        started.set()
        release.wait(5)

    monkeypatch.setattr(pipeline, "process_media", slow)
    pipeline.enqueue(901)
    assert started.wait(2)
    pipeline.enqueue(901)  # already running: ignored
    pipeline.enqueue(902)  # different media: waits its turn behind 901
    assert pipeline._worker.daemon  # stopping the server must not wait for a job
    release.set()
    deadline = time.time() + 3
    while len(runs) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert runs == [901, 902]
