"""A log of calls to the cloud services (language model, speech recognition) and why they failed.

One row per real call; a call that was skipped because the cloud is cooling down after a failure is not a call and
is not logged here (it shows up in the fallback counts of `usage`). Successes are logged too, so the admin page can
tell "the last five calls all failed" from "five failures spread over many good calls"."""

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlmodel import Session, func, select

from app import db
from app.config import settings
from app.models import CloudCall
from app.services.usage import day_start

log = logging.getLogger("uvicorn.error")

LLM, STT = "llm", "stt"
TIMEOUT, CONNECTION, HTTP, INVALID_JSON, OTHER = "timeout", "connection", "http", "invalid_json", "other"
EXCERPT = 200
BLOCKED_AFTER = 5  # this many recent real LLM calls, all refused with 403 / FreeTierError, mean the free model was switched off

_SECRET_PATTERNS = [
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+|basic\s+)?[^\s,\"'}]+"), r"\1***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***"),
    (re.compile(r"(?i)((?:api[_-]?key|key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'&}]+"), r"\1***"),
    (re.compile(r"\b(?:sk|gsk|pk)[-_][A-Za-z0-9_-]{8,}"), "***"),
]


def scrub(text: object, limit: int = EXCERPT) -> str:
    """A short excerpt that is safe to store and show: no API keys, no Authorization headers, one line, at most `limit` characters."""
    out = str(text)
    for secret in (settings.cloud_api_key, settings.stt_api_key):
        if secret and len(secret) >= 6:
            out = out.replace(secret, "***")
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return " ".join(out.split())[:limit]


def classify(error: BaseException) -> str:
    """timeout / connection for what httpx raised; the callers name http and invalid_json themselves."""
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return TIMEOUT
    if isinstance(error, httpx.HTTPError):
        return CONNECTION
    return OTHER


def record(service: str, ok: bool, *, status_code: int | None = None, error_class: str = "", message: str = "") -> None:
    """Log one real call. Never raises: logging must not break the request."""
    try:
        with Session(db.engine) as session:
            session.add(CloudCall(service=service, ok=ok, status_code=status_code, error_class=error_class, message=scrub(message)))
            session.commit()
    except Exception:  # noqa: BLE001
        log.warning("could not log a %s cloud call", service, exc_info=True)


def failure_reason(row) -> str:
    return f"{row.error_class} {row.status_code}" if row.status_code else row.error_class


def _count_by_reason(session: Session, service: str, since: datetime) -> dict[tuple[str, int | None], int]:
    rows = session.exec(
        select(CloudCall.error_class, CloudCall.status_code, func.count()).where(
            CloudCall.service == service, CloudCall.ok == False, CloudCall.created_at >= since  # noqa: E712
        ).group_by(CloudCall.error_class, CloudCall.status_code)
    ).all()
    return {(cls, code): int(n) for cls, code, n in rows}


def summary(session: Session, service: str) -> dict:
    """Failures today and in the last 7 days grouped by reason, and the latest failure."""
    today, week = _count_by_reason(session, service, day_start()), _count_by_reason(session, service, datetime.now(timezone.utc) - timedelta(days=7))
    reasons = [
        {"error_class": cls, "status_code": code, "today": today.get(key, 0), "week": n}
        for key, n in sorted(week.items(), key=lambda kv: -kv[1]) for cls, code in [key]
    ]
    last = session.exec(select(CloudCall).where(CloudCall.service == service, CloudCall.ok == False).order_by(CloudCall.created_at.desc(), CloudCall.id.desc())).first()  # noqa: E712
    calls = int(session.exec(select(func.count()).select_from(CloudCall).where(CloudCall.service == service, CloudCall.created_at >= day_start())).one())
    return {
        "calls_today": calls,
        "reasons": reasons,
        "last_failure": None if not last else {
            "at": last.created_at.replace(tzinfo=last.created_at.tzinfo or timezone.utc).isoformat(), "error_class": last.error_class,
            "status_code": last.status_code, "message": last.message,
        },
    }


def llm_looks_disabled(session: Session) -> bool:
    """The last `BLOCKED_AFTER` real language-model calls were all refused with HTTP 403 or a FreeTierError."""
    rows = session.exec(select(CloudCall).where(CloudCall.service == LLM).order_by(CloudCall.id.desc()).limit(BLOCKED_AFTER)).all()
    return len(rows) == BLOCKED_AFTER and all(not r.ok and (r.status_code == 403 or "FreeTierError" in r.message) for r in rows)
