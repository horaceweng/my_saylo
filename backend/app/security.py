"""Headers every response carries. The app is served from one address, so there is no CORS (nothing else may call it)."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
