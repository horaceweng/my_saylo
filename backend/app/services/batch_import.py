"""Bring in a video or podcast episode that was already transcribed and translated somewhere else
(the Colab batch pipeline, see `english-app/colab/`) — no speech recognition or translation runs here.

The learner processed a large batch of material on a separate machine (a Colab GPU); this only writes
already-finished results into the database, exactly as if `services/pipeline.py` had made them here."""

import hashlib
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models import Media, Segment, Word
from app.services.grading import grade
from app.services.youtube import extract_video_id


class BatchImportError(ValueError):
    """The result data does not look like a finished job; the message says what is wrong."""


@dataclass
class WordIn:
    text: str
    start: float
    end: float
    prob: float = 1.0


@dataclass
class SegmentIn:
    text: str
    start: float
    end: float
    translation: str = ""
    words: list[WordIn] = field(default_factory=list)


@dataclass
class ImportItem:
    kind: str  # video | podcast
    source_url: str
    title: str = ""
    thumbnail: str = ""
    duration: float = 0.0
    segments: list[SegmentIn] = field(default_factory=list)


def _external_id(item: ImportItem) -> str:
    if item.kind == "video":
        found = extract_video_id(item.source_url)
        if found:
            return found
    # a podcast episode, or a video link id extraction did not recognise: a stable hash of the link,
    # the same scheme podcasts.py uses for episodes added by hand
    return hashlib.sha1(item.source_url.encode()).hexdigest()[:11]


def _thumbnail(item: ImportItem, external_id: str) -> str:
    if item.thumbnail:
        return item.thumbnail
    if item.kind == "video" and extract_video_id(item.source_url):
        return f"https://i.ytimg.com/vi/{external_id}/hqdefault.jpg"
    return ""


def parse_item(data: dict) -> ImportItem:
    """The dict shape a Colab result file holds, turned into `ImportItem`. Raises `BatchImportError` on
    anything that would leave a broken row (a missing field, sentences with no words, times going backwards)."""
    try:
        kind = data["kind"]
        source_url = data["source_url"]
        raw_segments = data["segments"]
    except KeyError as e:
        raise BatchImportError(f"缺少欄位：{e}") from e
    if kind not in ("video", "podcast"):
        raise BatchImportError(f"不支援的種類：{kind}")
    if not source_url:
        raise BatchImportError("缺少 source_url")
    segments: list[SegmentIn] = []
    for i, raw in enumerate(raw_segments):
        try:
            words = [WordIn(w["text"], float(w["start"]), float(w["end"]), float(w.get("prob", 1.0))) for w in raw.get("words", [])]
            seg = SegmentIn(text=raw["text"], start=float(raw["start"]), end=float(raw["end"]), translation=raw.get("translation", ""), words=words)
        except (KeyError, TypeError, ValueError) as e:
            raise BatchImportError(f"第 {i + 1}句的資料不完整：{e}") from e
        if seg.end < seg.start:
            raise BatchImportError(f"第 {i + 1} 句的結束時間早於開始時間")
        segments.append(seg)
    return ImportItem(
        kind=kind, source_url=source_url, title=data.get("title", ""), thumbnail=data.get("thumbnail", ""),
        duration=float(data.get("duration") or 0), segments=segments,
    )


def import_item(session: Session, item: ImportItem) -> Media | None:
    """Write one finished item into the database. Returns the new `Media`, or None when a video or episode
    with the same source link is already there (nothing is changed or duplicated)."""
    existing = session.exec(select(Media).where(Media.kind == item.kind, Media.source_url == item.source_url)).first()
    if existing is not None:
        return None
    if not item.segments:
        raise BatchImportError("沒有任何句子可以匯入")

    external_id = _external_id(item)
    duration = item.duration or item.segments[-1].end
    level, score, _ = grade(seg.text for seg in item.segments)
    media = Media(
        kind=item.kind, source_url=item.source_url, external_id=external_id,
        title=item.title or f"（未命名，{item.kind}）", thumbnail=_thumbnail(item, external_id),
        duration=duration, status="ready", progress=100, transcribed=True, level=level, score=score,
    )
    session.add(media)
    session.flush()  # media.id is needed for the segments below

    for idx, seg in enumerate(item.segments):
        row = Segment(media_id=media.id, idx=idx, start=seg.start, end=seg.end, text=seg.text, translation=seg.translation)
        session.add(row)
        session.flush()
        for j, w in enumerate(seg.words):
            session.add(Word(segment_id=row.id, idx=j, text=w.text, start=w.start, end=w.end, prob=w.prob))

    session.commit()
    session.refresh(media)
    return media
