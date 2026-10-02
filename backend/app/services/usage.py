"""What each user has used today, the daily limits, and notes about the cloud failing over to this Mac.

A day ends at midnight in `settings.quota_timezone` (Asia/Taipei). Admins are never limited. Answers that came
from the AI cache are not charged: callers charge only when the model is really going to be asked."""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlmodel import Session, func, select

from app import db
from app.config import settings
from app.models import UsageEvent, User

log = logging.getLogger("uvicorn.error")

MEDIA, AUDIO_MINUTES, AI = "media", "audio_minutes", "ai"
FALLBACK_LLM, FALLBACK_STT = "fallback_llm", "fallback_stt"


def _zone():
    try:
        return ZoneInfo(settings.quota_timezone)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=8))  # no time zone database on this machine: Taipei has no summer time anyway


def _zone_label() -> str:
    return "台北時間" if settings.quota_timezone == "Asia/Taipei" else settings.quota_timezone


def day_start(now: datetime | None = None) -> datetime:
    """Midnight that began today (UTC)."""
    local = (now or datetime.now(timezone.utc)).astimezone(_zone())
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def next_reset(now: datetime | None = None) -> datetime:
    start = day_start(now).astimezone(_zone())
    return (start + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def used_today(session: Session, user_id: int, kind: str) -> float:
    return float(session.exec(
        select(func.coalesce(func.sum(UsageEvent.amount), 0.0)).where(
            UsageEvent.user_id == user_id, UsageEvent.kind == kind, UsageEvent.created_at >= day_start()
        )
    ).one())


def record(session: Session, user_id: int | None, kind: str, amount: float = 1.0) -> None:
    session.add(UsageEvent(user_id=user_id, kind=kind, amount=amount))
    session.commit()


def record_system(kind: str) -> None:
    """Note an event that belongs to no user (the cloud failed). Never raises: counting must not break the request."""
    try:
        with Session(db.engine) as session:
            record(session, None, kind)
    except Exception:  # noqa: BLE001
        log.warning("could not record %s", kind, exc_info=True)


def limits() -> dict[str, float]:
    return {MEDIA: settings.quota_media_per_day, AUDIO_MINUTES: settings.quota_audio_minutes_per_day, AI: settings.quota_ai_requests_per_day}


def _too_many(what: str, used: float, limit: float, unit: str) -> HTTPException:
    reset = next_reset()
    local = reset.astimezone(_zone())
    seconds = max(1, int((reset - datetime.now(timezone.utc)).total_seconds()))
    message = f"{what}已達上限（{used:g}／{limit:g} {unit}）。將在 {local:%m/%d %H:%M}（{_zone_label()}）重置，之後就可以再用。"
    return HTTPException(429, message, headers={"Retry-After": str(seconds)})


def charge_ai(session: Session, user: User) -> None:
    """Count one question to the AI, or refuse (429) when the day's allowance is used up."""
    if user.is_admin:
        return
    used = used_today(session, user.id, AI)
    if used + 1 > settings.quota_ai_requests_per_day:
        raise _too_many("今天的 AI 使用次數", used, settings.quota_ai_requests_per_day, "次")
    record(session, user.id, AI)


def check_media_length(user: User, seconds: float) -> None:
    if not user.is_admin and seconds > settings.max_media_minutes * 60:
        raise HTTPException(413, f"這支影片／音檔太長（{seconds / 60:.0f} 分鐘），單支最長 {settings.max_media_minutes} 分鐘")


def charge_media(session: Session, user: User, seconds: float = 0.0) -> None:
    """Count one new video or episode and its length, or refuse. `seconds` 0 means the length is not known yet."""
    if user.is_admin:
        return
    check_media_length(user, seconds)
    count = used_today(session, user.id, MEDIA)
    if count + 1 > settings.quota_media_per_day:
        raise _too_many("今天新增的影片／Podcast 數量", count, settings.quota_media_per_day, "支")
    minutes = seconds / 60
    used = used_today(session, user.id, AUDIO_MINUTES)
    if used + minutes > settings.quota_audio_minutes_per_day:
        raise _too_many("今天處理的音訊長度", round(used), settings.quota_audio_minutes_per_day, "分鐘")
    record(session, user.id, MEDIA)
    if minutes:
        record(session, user.id, AUDIO_MINUTES, minutes)


def upload_limit_bytes(user: User, default_max: int) -> int:
    """How large a file this user may upload: admins keep the endpoint's own ceiling."""
    return default_max if user.is_admin else min(default_max, settings.max_upload_mb * 1024 * 1024)


def today_summary(session: Session) -> dict[int, dict[str, float]]:
    """Per user id: what was used today."""
    rows = session.exec(
        select(UsageEvent.user_id, UsageEvent.kind, func.sum(UsageEvent.amount))
        .where(UsageEvent.created_at >= day_start(), UsageEvent.user_id.is_not(None))
        .group_by(UsageEvent.user_id, UsageEvent.kind)
    ).all()
    out: dict[int, dict[str, float]] = {}
    for user_id, kind, total in rows:
        out.setdefault(user_id, {})[kind] = float(total)
    return out


def fallback_counts(session: Session) -> dict[str, dict[str, int]]:
    """How often the cloud failed over to this Mac: today and in the last 7 days."""
    out: dict[str, dict[str, int]] = {}
    for kind in (FALLBACK_LLM, FALLBACK_STT):
        def count(since: datetime) -> int:
            return int(session.exec(select(func.count()).select_from(UsageEvent).where(UsageEvent.kind == kind, UsageEvent.created_at >= since)).one())

        out[kind] = {"today": count(day_start()), "week": count(datetime.now(timezone.utc) - timedelta(days=7))}
    return out
