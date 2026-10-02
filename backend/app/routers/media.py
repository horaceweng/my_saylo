from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import case
from sqlmodel import Session, delete, func, select

from app.db import get_session
from app.deps import admin_user, current_user
from app.models import Media, Segment, Setting, User, Word
from app.services import pipeline, usage, youtube
from app.services.grading import GRADING_VERSION, grade

router = APIRouter(prefix="/api/media", tags=["media"])


class CreateMedia(BaseModel):
    url: str


class Focus(BaseModel):
    idx: int


def regrade_media(engine) -> int:
    """Grade every finished video and podcast again when the grading method has changed since they were
    graded (see services/grading.py). Returns how many were updated (0 when everything is up to date)."""
    with Session(engine) as session:
        marker = session.get(Setting, "media_grading_version")
        if marker and marker.value == GRADING_VERSION:
            return 0
        updated = 0
        for media in session.exec(select(Media).where(Media.status == "ready")).all():
            texts = session.exec(select(Segment.text).where(Segment.media_id == media.id).order_by(Segment.idx)).all()
            level, score, _ = grade(texts)
            if (media.level, media.score) != (level, score):
                media.level, media.score = level, score
                session.add(media)
                updated += 1
        session.merge(Setting(key="media_grading_version", value=GRADING_VERSION))
        session.commit()
        return updated


def media_stats(session: Session, ids: list[int]) -> dict[int, dict]:
    """Sentence counts per media: how many exist, how many are translated, how far the transcript reaches."""
    if not ids:
        return {}
    rows = session.exec(
        select(
            Segment.media_id, func.count(), func.coalesce(func.sum(case((Segment.translation != "", 1), else_=0)), 0), func.max(Segment.end)
        ).where(Segment.media_id.in_(ids)).group_by(Segment.media_id)
    ).all()
    return {mid: {"sentence_count": n, "translated_count": tr, "covered_until": end or 0.0} for mid, n, tr, end in rows}


def media_out(media: Media, stats: dict | None = None) -> dict:
    """The media row plus what has been made so far. `playable`: enough is ready to start studying."""
    st = {"sentence_count": 0, "translated_count": 0, "covered_until": 0.0, **(stats or {})}
    playable = media.status == "ready" or st["translated_count"] >= pipeline.PLAYABLE_AFTER
    # "Waiting, N jobs ahead": only meaningful until the worker picks it up.
    position = pipeline.queue_position(media.id) if media.status == "pending" else 0
    return {**media.model_dump(), **st, "playable": playable, "queue_position": position}


def _segments(session: Session, media_id: int, from_idx: int = 0) -> list[dict]:
    segments = session.exec(
        select(Segment).where(Segment.media_id == media_id, Segment.idx >= from_idx).order_by(Segment.idx)
    ).all()
    seg_ids = [s.id for s in segments]
    words_by_seg: dict[int, list[dict]] = {sid: [] for sid in seg_ids}
    if seg_ids:
        for w in session.exec(select(Word).where(Word.segment_id.in_(seg_ids)).order_by(Word.segment_id, Word.idx)):
            words_by_seg[w.segment_id].append({"text": w.text, "start": w.start, "end": w.end})
    return [
        {"id": s.id, "idx": s.idx, "start": s.start, "end": s.end, "text": s.text,
         "translation": s.translation, "words": words_by_seg[s.id]}
        for s in segments
    ]


@router.post("")
async def create_media(body: CreateMedia, session: Session = Depends(get_session), user: User = Depends(current_user)):
    video_id = youtube.extract_video_id(body.url)
    if not video_id:
        raise HTTPException(400, "這不是有效的 YouTube 網址")
    existing = session.exec(select(Media).where(Media.external_id == video_id, Media.kind == "video")).first()
    if existing:
        return media_out(existing, media_stats(session, [existing.id]).get(existing.id))
    try:
        info = await youtube.fetch_info_async(video_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"無法取得影片資訊：{str(e)[:200]}") from e
    usage.charge_media(session, user, info.get("duration", 0))
    media = Media(kind="video", source_url=body.url, external_id=video_id, added_by=user.id, **info)
    session.add(media)
    session.commit()
    session.refresh(media)
    pipeline.enqueue(media.id)
    return media_out(media)


@router.get("")
def list_media(kind: str | None = None, session: Session = Depends(get_session)):
    stmt = select(Media).order_by(Media.created_at.desc())
    if kind:
        stmt = stmt.where(Media.kind == kind)
    rows = session.exec(stmt).all()
    stats = media_stats(session, [m.id for m in rows])
    return [media_out(m, stats.get(m.id)) for m in rows]


@router.get("/{media_id}")
def get_media(media_id: int, session: Session = Depends(get_session)):
    media = session.get(Media, media_id)
    if not media:
        raise HTTPException(404, "找不到這個影片")
    return {**media_out(media, media_stats(session, [media_id]).get(media_id)), "segments": _segments(session, media_id)}


@router.get("/{media_id}/updates")
def media_updates(media_id: int, known: int = 0, missing_from: int = 0, session: Session = Depends(get_session)):
    """What appeared since the page last looked, without sending the whole transcript again.
    `known`: how many sentences the page has (those from that index on are sent in full).
    `missing_from`: the first sentence the page still lacks a translation for; translations from there on are sent."""
    media = session.get(Media, media_id)
    if not media:
        raise HTTPException(404, "找不到這個影片")
    translations = {
        str(idx): text
        for idx, text in session.exec(
            select(Segment.idx, Segment.translation).where(
                Segment.media_id == media_id, Segment.idx >= missing_from, Segment.idx < known, Segment.translation != ""
            )
        )
    }
    return {
        **media_out(media, media_stats(session, [media_id]).get(media_id)),
        "new_segments": _segments(session, media_id, from_idx=known),
        "translations": translations,
    }


@router.get("/{media_id}/audio")
def media_audio(media_id: int, session: Session = Depends(get_session)):
    """The audio file itself (supports seeking), for the podcast player."""
    media = session.get(Media, media_id)
    if not media or not media.audio_path or not Path(media.audio_path).exists():
        raise HTTPException(404, "找不到音檔")
    return FileResponse(media.audio_path)


@router.post("/{media_id}/focus")
def set_focus(media_id: int, body: Focus):
    """Tell the translator where the learner is, so it works on the sentences around that point first."""
    pipeline.set_focus(media_id, body.idx)
    return {"ok": True}


@router.post("/{media_id}/retry")
def retry_media(media_id: int, restart: bool = False, session: Session = Depends(get_session)):
    """Continue an interrupted or failed job from where it stopped. `restart=true` throws away the
    transcript and translations and does everything again."""
    media = session.get(Media, media_id)
    if not media:
        raise HTTPException(404, "找不到這個影片")
    if restart:
        seg_ids = session.exec(select(Segment.id).where(Segment.media_id == media_id)).all()
        if seg_ids:
            session.exec(delete(Word).where(Word.segment_id.in_(seg_ids)))
        session.exec(delete(Segment).where(Segment.media_id == media_id))
    media.status, media.progress, media.error = "pending", 0, ""
    if restart:
        media.transcribed = False
    session.add(media)
    session.commit()
    session.refresh(media)
    pipeline.enqueue(media_id)
    return media_out(media, media_stats(session, [media_id]).get(media_id))


@router.delete("/{media_id}")
def delete_media(media_id: int, session: Session = Depends(get_session), _: User = Depends(admin_user)):
    media = session.get(Media, media_id)
    if not media:
        raise HTTPException(404, "找不到這個影片")
    seg_ids = session.exec(select(Segment.id).where(Segment.media_id == media_id)).all()
    if seg_ids:
        session.exec(delete(Word).where(Word.segment_id.in_(seg_ids)))
    session.exec(delete(Segment).where(Segment.media_id == media_id))
    audio_path = media.audio_path
    session.delete(media)
    session.commit()
    # The downloaded audio is only useful for this entry; free the disk unless another entry shares the file.
    if audio_path and not session.exec(select(Media.id).where(Media.audio_path == audio_path)).first():
        Path(audio_path).unlink(missing_ok=True)
    return {"ok": True}
