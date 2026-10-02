"""Background job: download audio → transcribe → split sentences → translate."""

import asyncio
import logging
import queue
import threading
import time

from sqlmodel import Session, delete, func, select

from app.db import engine
from app.models import Media, Segment, User, Word
from app.config import settings
from app.services import podcast, prompts, usage, youtube
from app.services.grading import grade
from app.services.llm import LLMError, chat_json, make_provider
from app.services.chunked import transcribe_in_pieces
from app.services.segmenter import Sentence, split_sentences
from app.services.transcribe import SAMPLE_RATE, load_audio, transcribe_span

log = logging.getLogger("uvicorn.error")  # shows up in the server output

BATCH_SIZE = 10
PLAYABLE_AFTER = 20  # translated sentences after which the video can be opened while the rest is still being made
LOOKAHEAD = 40  # while transcription goes on, keep this many sentences after the learner's position translated
UNFINISHED = ("pending", "downloading", "transcribing", "translating")

# Whisper and the LLM are both heavy: one worker thread handles one media job at a time. It is a daemon
# thread, so stopping the server never waits for a job to finish (a stale process used to linger for
# an hour and keep working on the same video). Interrupted jobs pick up where they stopped, see _run.
_work: "queue.Queue[int]" = queue.Queue()
_queued: set[int] = set()  # waiting or running
_waiting: list[int] = []  # waiting, in the order the worker will take them
_running: int | None = None
_state = threading.Lock()
_worker: threading.Thread | None = None


def queue_position(media_id: int) -> int:
    """How many jobs are ahead of this one (the running one counts); 0 when it is running or not queued."""
    with _state:
        if media_id not in _waiting:
            return 0
        return _waiting.index(media_id) + (1 if _running is not None else 0)


class MediaDeleted(Exception):
    """The learner deleted the video while it was being processed: stop quietly."""


class MediaTimeout(Exception):
    """A job used more than its allowance (audio length x 3 + 10 minutes): it is marked failed and can be retried."""


def time_budget(duration: float) -> float:
    return duration * settings.media_time_factor + settings.media_time_extra_seconds


def _check_time(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise MediaTimeout("處理時間太長，已先停止（已完成的部分都保留了）。按「繼續處理」可以從中斷的地方接著做")


def _set(media_id: int, **fields) -> None:
    with Session(engine) as session:
        media = session.get(Media, media_id)
        if media is None:
            raise MediaDeleted(media_id)
        for k, v in fields.items():
            setattr(media, k, v)
        session.add(media)
        session.commit()


async def translate_sentences(sentences: list[str], provider=None) -> list[str]:
    """Translate one batch. The model keys answers by sentence number, so a skipped
    sentence is detected and only that sentence is retried on its own."""
    provider = provider or make_provider()

    async def ask(batch: list[str]) -> dict[str, str]:
        try:
            result = await chat_json(provider, prompts.TRANSLATE_SYSTEM, prompts.translate_user_prompt(batch), prompts.TranslationBatch)
        except LLMError:
            return {}
        return {k.strip(): v.strip() for k, v in result.translations.items() if v.strip()}

    got = await ask(sentences)
    out: list[str] = []
    for i, sentence in enumerate(sentences):
        text = got.get(str(i + 1))
        if not text:
            text = (await ask([sentence])).get("1", "")
        out.append(text)
    return out


def process_media(media_id: int) -> None:
    try:
        _run(media_id)
    except MediaDeleted:
        log.info("media %s was deleted while it was being processed; stopped", media_id)
        _focus.pop(media_id, None)
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        log.exception("media %s failed", media_id)
        try:
            _set(media_id, status="error", error=str(e)[:500])
        except MediaDeleted:
            pass


def enqueue(media_id: int) -> None:
    """Queue a media job (no-op if it is already queued or running) and make sure the worker exists."""
    global _worker
    with _state:
        if media_id in _queued:
            return
        _queued.add(media_id)
        _waiting.append(media_id)
        _work.put(media_id)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="media-worker", daemon=True)
            _worker.start()


def _worker_loop() -> None:
    global _running
    while True:
        media_id = _work.get()
        with _state:
            if media_id in _waiting:
                _waiting.remove(media_id)
            _running = media_id
        try:
            process_media(media_id)
        finally:
            with _state:
                _running = None
                _queued.discard(media_id)


def resume_unfinished() -> list[int]:
    """Queue every job that was cut short by a restart. It continues from what is already saved."""
    with Session(engine) as session:
        ids = list(session.exec(select(Media.id).where(Media.status.in_(UNFINISHED)).order_by(Media.id)))
    for media_id in ids:
        enqueue(media_id)
    return ids


# The sentence the learner is at, per media: translation works outward from there, so jumping ahead in a
# long video does not mean waiting for everything before it.
_focus: dict[int, int] = {}


def set_focus(media_id: int, idx: int) -> None:
    _focus[media_id] = max(0, idx)


def _counts(session: Session, media_id: int) -> tuple[int, int]:
    total = session.exec(select(func.count()).select_from(Segment).where(Segment.media_id == media_id)).one()
    translated = session.exec(
        select(func.count()).select_from(Segment).where(Segment.media_id == media_id, Segment.translation != "")
    ).one()
    return total, translated


def _save_sentences(media_id: int, sentences: list[Sentence], first_idx: int) -> None:
    with Session(engine) as session:
        for i, s in enumerate(sentences, start=first_idx):
            seg = Segment(media_id=media_id, idx=i, start=s.start, end=s.end, text=s.text)
            session.add(seg)
            session.flush()
            for j, w in enumerate(s.words):
                session.add(Word(segment_id=seg.id, idx=j, text=w.text.strip(), start=w.start, end=w.end, prob=w.prob))
        session.commit()


def _translate_pending(media_id: int, attempted: set[int], window: int | None = None, report=None, deadline: float | None = None) -> int:
    """Translate untranslated sentences one batch at a time, the ones nearest the learner first.
    `window`: only the sentences from the learner's position up to that many after it (None: all of them,
    continuing from the start once the end is reached). A sentence that comes back empty is not retried in
    the same run. Returns how many were translated."""
    done = 0
    while True:
        _check_time(deadline)
        focus = _focus.get(media_id, 0)
        with Session(engine) as session:
            rows = [
                (seg_id, idx, text)
                for seg_id, idx, text in session.exec(
                    select(Segment.id, Segment.idx, Segment.text)
                    .where(Segment.media_id == media_id, Segment.translation == "").order_by(Segment.idx)
                )
                if seg_id not in attempted
            ]
        if window is not None:
            rows = [r for r in rows if focus <= r[1] < focus + window]
        if not rows:
            return done
        batch = ([r for r in rows if r[1] >= focus] + [r for r in rows if r[1] < focus])[:BATCH_SIZE]
        translations = asyncio.run(translate_sentences([text for _, _, text in batch]))
        with Session(engine) as session:
            if session.get(Media, media_id) is None:
                raise MediaDeleted(media_id)
            for (seg_id, _, _), translation in zip(batch, translations):
                seg = session.get(Segment, seg_id)
                if seg is None:
                    raise MediaDeleted(media_id)
                seg.translation = translation
                session.add(seg)
            session.commit()
        attempted.update(seg_id for seg_id, _, _ in batch)
        done += len(batch)
        if report:
            report(*_counts_now(media_id))


def _counts_now(media_id: int) -> tuple[int, int]:
    with Session(engine) as session:
        return _counts(session, media_id)


def _grade(media_id: int) -> tuple[str, float]:
    """Estimate the transcript's difficulty (A2/B1/B2/C1+), the same way as books (services/grading.py)."""
    with Session(engine) as session:
        texts = session.exec(select(Segment.text).where(Segment.media_id == media_id).order_by(Segment.idx)).all()
    level, score, _ = grade(texts)
    return level, score


def _account_length(media_id: int, seconds: float, first_time: bool) -> None:
    """The length of an episode whose feed did not say how long it is, known now: refuse one over the limit for an
    ordinary user and count its minutes against their day (a video's length was counted when it was added)."""
    with Session(engine) as session:
        media = session.get(Media, media_id)
        owner = session.get(User, media.added_by) if media and media.added_by else None
        if owner is None or owner.is_admin:
            return
        if seconds > settings.max_media_minutes * 60:
            raise RuntimeError(f"這個音檔太長（{seconds / 60:.0f} 分鐘），單支最長 {settings.max_media_minutes} 分鐘")
        if first_time and seconds:
            usage.record(session, owner.id, usage.AUDIO_MINUTES, seconds / 60)


def _run(media_id: int) -> None:
    """download → transcribe in pieces → translate, skipping whatever an earlier run finished.

    The first sentences are translated as soon as the first piece is transcribed, so the video can be
    opened after seconds; the rest of the transcript and translation is filled in behind the learner."""
    with Session(engine) as session:
        media = session.get(Media, media_id)
        external_id, audio_path, transcribed = media.external_id, media.audio_path, media.transcribed
        kind, source_url, known_duration = media.kind, media.source_url, media.duration

    timings: dict[str, float] = {}
    started = time.monotonic()
    attempted: set[int] = set()
    deadline: float | None = started + time_budget(known_duration) if known_duration else None

    if not transcribed:
        if not audio_path:
            _set(media_id, status="downloading", progress=2, error="")
            if kind == "podcast":
                path = podcast.download_audio(
                    source_url, settings.data_dir / "audio", progress=lambda f: _set(media_id, progress=2 + int(8 * f))
                )
            else:
                path = youtube.download_audio(external_id)
            audio_path = str(path)
            _set(media_id, audio_path=audio_path, progress=10)
        timings["download"] = time.monotonic() - started

        _set(media_id, status="transcribing", progress=10, error="")
        t = time.monotonic()
        audio = load_audio(audio_path)
        duration = len(audio) / SAMPLE_RATE
        if abs(duration - known_duration) > 1:
            _set(media_id, duration=round(duration, 1))  # feeds often lack a duration or round it
        _account_length(media_id, duration, first_time=known_duration == 0)
        deadline = started + time_budget(duration)
        with Session(engine) as session:
            saved_until = session.exec(select(func.max(Segment.end)).where(Segment.media_id == media_id)).one() or 0.0
            saved = session.exec(select(func.count()).select_from(Segment).where(Segment.media_id == media_id)).one()
        doubtful = []
        for piece in transcribe_in_pieces(lambda a, b: transcribe_span(audio, a, b), duration, start=saved_until):
            _set(media_id, progress=10 + int(40 * min(1.0, piece.frontier / duration)))  # raises if the video was deleted
            _save_sentences(media_id, piece.sentences, first_idx=saved)
            saved += len(piece.sentences)
            doubtful += piece.doubtful
            _translate_pending(media_id, attempted, window=LOOKAHEAD, deadline=deadline)  # the first ones open the video early
            _check_time(deadline)
        if saved == 0:
            # Nothing looked reliable anywhere (poor audio, heavy accent): show it rather than erase it.
            fallback = split_sentences(doubtful)
            if not fallback:
                raise RuntimeError("沒有辨識到任何英文語音")
            _save_sentences(media_id, fallback, first_idx=0)
        _set(media_id, transcribed=True)
        timings["transcribe"] = time.monotonic() - t

    _set(media_id, status="translating", progress=50, error="")
    t = time.monotonic()

    def report(total: int, translated: int) -> None:
        _set(media_id, progress=50 + int(50 * translated / max(1, total)))

    translated_now = _translate_pending(media_id, attempted, report=report, deadline=deadline)
    total, _ = _counts_now(media_id)
    timings["translate"] = time.monotonic() - t
    level, score = _grade(media_id)
    _set(media_id, status="ready", progress=100, level=level, score=score)
    _focus.pop(media_id, None)
    log.info(
        "media %s ready: %d sentences (%d translated after the first pieces) | %s | total %.0fs",
        media_id, total, translated_now, ", ".join(f"{k} {v:.0f}s" for k, v in timings.items()), time.monotonic() - started,
    )
