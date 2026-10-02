"""Simple in-memory rate limits: sign-ins per IP address, other API calls per user.

The counts live in this process only (a restart forgets them), which is fine for one small server."""

import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from app.config import settings

WINDOW = 60.0
_hits: dict[str, deque[float]] = {}
_lock = threading.Lock()
_swept = 0.0


def reset() -> None:
    global _swept
    with _lock:
        _hits.clear()
        _swept = 0.0


def _sweep(now: float) -> None:
    """Forget keys that have been quiet for a whole window, so the table cannot grow without end."""
    global _swept
    if now - _swept < WINDOW:
        return
    _swept = now
    for key in [k for k, q in _hits.items() if not q or now - q[-1] > WINDOW]:
        del _hits[key]


def hit(key: str, limit: int, what: str, now: float | None = None) -> None:
    """Count one request for `key`; raises 429 when more than `limit` happened in the last minute."""
    now = time.monotonic() if now is None else now
    with _lock:
        _sweep(now)
        q = _hits.setdefault(key, deque())
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= limit:
            wait = max(1, int(WINDOW - (now - q[0])) + 1)
            raise HTTPException(429, f"{what}太頻繁了，請 {wait} 秒後再試", headers={"Retry-After": str(wait)})
        q.append(now)


def client_ip(request: Request) -> str:
    """The caller's address. X-Forwarded-For is only believed when the direct peer is this machine (the Tailscale
    Funnel proxy); then its last entry is the one our own proxy added, earlier ones can be made up by the caller.
    Started with `--proxy-headers --forwarded-allow-ips 127.0.0.1` (scripts/start-prod.sh), uvicorn has already put
    that same address into request.client, so the peer here is the real caller and the header is not read a second
    time; without those flags this function does the job alone. Both ways give the same answer."""
    peer = request.client.host if request.client else "unknown"
    if peer == "127.0.0.1":
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return peer


def limit_auth(request: Request) -> None:
    hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute, "登入／註冊嘗試")


def limit_user(user_id: int) -> None:
    hit(f"user:{user_id}", settings.rate_limit_api_per_minute, "操作")
