"""Headers every response carries. The app is served from one address, so there is no CORS (nothing else may call it)."""

import json
import re

from sqlmodel import Session
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import db
from app.config import settings
from app.services import auth

# What the page loads: its own script and styles, the YouTube player (script + iframe), thumbnails from any https site
# (podcast and news covers), audio from itself or recorded in the browser (blob:). Nothing else may run or load.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://www.youtube.com https://s.ytimg.com",
    "style-src 'self' 'unsafe-inline'",  # React sets style attributes (progress bars, highlights)
    "img-src 'self' data: https:",
    "media-src 'self' blob:",
    "connect-src 'self' blob:",
    "font-src 'self' data:",
    "frame-src https://www.youtube.com https://www.youtube-nocookie.com",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "microphone=(self)",
    "Content-Security-Policy": CSP,
}
HSTS = "max-age=15552000"  # 180 days, https only; no includeSubDomains (the host is a shared Tailscale name)


class SecurityHeaders:
    """Plain ASGI middleware (not BaseHTTPMiddleware) so streamed answers are passed through untouched."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"].startswith("/api/")
        secure = scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    headers[name] = value
                if secure:
                    headers["Strict-Transport-Security"] = HSTS
                if is_api and "cache-control" not in headers and "json" in headers.get("content-type", ""):
                    headers["Cache-Control"] = "no-store"  # answers are one person's data (audio files may be cached)
            await send(message)

        await self.app(scope, receive, send_with_headers)


MB = 1024 * 1024
JSON_BODY_LIMIT = 1 * MB
MULTIPART_OVERHEAD = 1 * MB
# The upload endpoints and the most a file may be there (admins; other users are held to `max_upload_mb` as well).
UPLOADS = [
    (re.compile(r"^/api/books/upload$"), 60 * MB),
    (re.compile(r"^/api/podcasts/upload$"), 600 * MB),
    (re.compile(r"^/api/segments/\d+/recordings$"), 15 * MB),
]


class _TooLarge(BaseException):
    """Not an Exception on purpose: FastAPI turns any Exception while reading a body into a 400."""


class BodyLimit:
    """Refuses request bodies that are too large before they are read in. FastAPI reads a whole form upload (into
    memory, then a temporary file) before the endpoint runs, so the endpoint's own byte counting comes too late."""

    def __init__(self, app: ASGIApp):
        self.app = app

    def _limit(self, scope: Scope, headers: Headers) -> tuple[int, str]:
        """(most bytes the body may have, what to tell the sender when it has more)."""
        for pattern, ceiling in UPLOADS:
            if pattern.match(scope["path"]):
                if ceiling > settings.max_upload_mb * MB and not _is_admin(headers):
                    ceiling = settings.max_upload_mb * MB
                return ceiling + MULTIPART_OVERHEAD, f"檔案太大（超過 {ceiling // MB} MB）"
        return JSON_BODY_LIMIT, "傳送的內容太大"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        limit, message = self._limit(scope, headers)
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await self._refuse(send, message)
            return
        seen, started = 0, False

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if started:
                raise
            await self._refuse(send, message)

    @staticmethod
    async def _refuse(send: Send, message: str) -> None:
        body = json.dumps({"detail": message}, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})


def _is_admin(headers: Headers) -> bool:
    """Is the session cookie an admin's? (Only used to pick the upload ceiling; the endpoint checks the login for real.)"""
    cookie = headers.get("cookie", "")
    match = re.search(rf"(?:^|;\s*){auth.COOKIE}=([^;]+)", cookie)
    if not match:
        return False
    with Session(db.engine) as session:
        user = auth.user_for_token(session, match.group(1))
    return bool(user and user.is_admin)
