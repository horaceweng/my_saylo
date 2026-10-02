import asyncio
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.deps import admin_user, current_user
from app.models import Feed, Media, User
from app.routers.media import media_out, media_stats
from app.services import pipeline, podcast, safe_fetch, uploads, usage
from app.services.podcast import PodcastError

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])

MAX_UPLOAD_BYTES = 600 * 1024 * 1024


class CreatePodcast(BaseModel):
    audio_url: str
    title: str = Field(default="", max_length=300)
    thumbnail: str = Field(default="", max_length=1000)
    duration: float = Field(default=0.0, ge=0, le=86400)


@router.get("/feed")
async def look_up(url: str):
    """What a pasted link is: an RSS feed (with its episodes) or a direct audio file."""
    try:
        return await asyncio.to_thread(podcast.fetch_feed_or_audio, url)
    except PodcastError as e:
        raise HTTPException(400, str(e)) from e


class ChannelIn(BaseModel):
    url: str


def _channel_out(feed: Feed) -> dict:
    return {"id": feed.id, "title": feed.title, "url": feed.url, "image": feed.image}


def _channel(session: Session, channel_id: int) -> Feed:
    feed = session.get(Feed, channel_id)
    if not feed or feed.kind != "podcast":
        raise HTTPException(404, "找不到這個頻道")
    return feed


@router.get("/channels")
def list_channels(session: Session = Depends(get_session)):
    """The podcasts the learner follows."""
    return [_channel_out(f) for f in session.exec(select(Feed).where(Feed.kind == "podcast").order_by(Feed.id)).all()]


@router.post("/channels")
async def add_channel(body: ChannelIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Follow a podcast. The feed is opened once first, so a link that is not a podcast feed is refused with a reason."""
    try:
        url = podcast.check_url(body.url)
        existing = session.exec(select(Feed).where(Feed.kind == "podcast", Feed.url == url)).first()
        if existing:
            return _channel_out(existing)
        found = await asyncio.to_thread(podcast.fetch_feed_or_audio, url)
    except PodcastError as e:
        raise HTTPException(400, str(e)) from e
    if found["type"] != "feed":
        raise HTTPException(400, "這是單一音檔的連結，不是 Podcast 節目的 RSS 網址")
    feed = Feed(kind="podcast", url=url, title=found["title"] or url, image=found.get("image") or "", added_by=user.id)
    session.add(feed)
    session.commit()
    session.refresh(feed)
    return _channel_out(feed)


@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int, session: Session = Depends(get_session), _: User = Depends(admin_user)):
    """Stop following. Episodes already loaded stay in the library."""
    session.delete(_channel(session, channel_id))
    session.commit()
    return {"ok": True}


@router.get("/channels/{channel_id}/episodes")
async def channel_episodes(channel_id: int, session: Session = Depends(get_session)):
    """The channel's latest episodes, straight from its feed."""
    feed = _channel(session, channel_id)
    try:
        found = await asyncio.to_thread(podcast.fetch_feed_or_audio, feed.url)
    except PodcastError as e:
        raise HTTPException(502, str(e)) from e
    if found["type"] != "feed":
        raise HTTPException(502, "這個網址現在不是 Podcast RSS")
    return {"title": found["title"], "image": found.get("image") or feed.image, "episodes": found["episodes"]}


@router.post("")
def add_podcast(body: CreatePodcast, session: Session = Depends(get_session), user: User = Depends(current_user)):
    try:
        url = podcast.check_url(body.audio_url)
        safe_fetch.vet(url)  # refuse addresses on this machine or its networks now, not only when the download starts
    except (PodcastError, safe_fetch.FetchError) as e:
        raise HTTPException(400, str(e)) from e
    existing = session.exec(select(Media).where(Media.kind == "podcast", Media.source_url == url)).first()
    if existing:
        return media_out(existing, media_stats(session, [existing.id]).get(existing.id))
    usage.charge_media(session, user, body.duration)
    fallback_title = Path(url.split("?")[0]).stem.replace("_", " ").replace("-", " ") or "Podcast"
    media = Media(
        kind="podcast", source_url=url, external_id=hashlib.sha1(url.encode()).hexdigest()[:11],
        title=body.title.strip() or fallback_title, thumbnail=body.thumbnail, duration=body.duration, added_by=user.id,
    )
    session.add(media)
    session.commit()
    session.refresh(media)
    pipeline.enqueue(media.id)
    return media_out(media)


@router.post("/upload")
async def upload_podcast(file: UploadFile, title: str = Form(""), session: Session = Depends(get_session), user: User = Depends(current_user)):
    """An audio file from the learner's own computer."""
    name = file.filename or "audio"  # shown as a title only; the file on disk gets a name of our own
    ext = Path(name).suffix.lower()
    if ext not in podcast.AUDIO_EXTENSIONS:
        raise HTTPException(400, "請選擇音檔（mp3、m4a、wav、ogg、flac 等）")
    folder = settings.data_dir / "audio"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"upload_{uuid.uuid4().hex[:16]}{ext}"
    limit = usage.upload_limit_bytes(user, MAX_UPLOAD_BYTES)
    await uploads.save_stream(file, target, limit, f"音檔太大（超過 {limit // (1024 * 1024)} MB）")
    try:
        usage.check_media_length(user, await asyncio.to_thread(uploads.check_audio_file, target))
        usage.charge_media(session, user)  # its length is counted once the audio has been read (pipeline)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    media = Media(
        kind="podcast", source_url=f"upload:{name[:200]}", external_id=target.stem[-11:], audio_path=str(target),
        title=(title.strip() or Path(name).stem.replace("_", " "))[:300], added_by=user.id,
    )
    session.add(media)
    session.commit()
    session.refresh(media)
    pipeline.enqueue(media.id)
    return media_out(media)
