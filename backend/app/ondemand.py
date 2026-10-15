"""Run only while someone is using the app: launchd listens on 127.0.0.1:8000 and starts the server on the first
connection (socket activation); the server exits after `IDLE_SECONDS` without requests and without work in hand.
So when nobody uses it, nothing is in memory, not even the web server.

`python -m app.ondemand` is what scripts/start-prod.sh runs. Started by launchd with the socket (see
deploy/macmini/com.horaceweng.english-app.plist) it uses that socket and exits when idle; started any other way it
listens on 127.0.0.1:8000 itself and keeps running, like plain uvicorn.

"Work in hand" is anything that would be lost or cut short by exiting: a request still being answered (that includes
a streaming explanation), a video or podcast being processed or waiting in line, or a local model in use."""

import ctypes
import logging
import socket
import threading
import time

log = logging.getLogger("uvicorn.error")

IDLE_SECONDS = 15 * 60
CHECK_SECONDS = 30


class Activity:
    """ASGI middleware: counts the requests being answered and remembers when the last one ended."""

    in_flight = 0
    last_seen = time.monotonic()
    _lock = threading.Lock()

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        cls = type(self)
        with cls._lock:
            cls.in_flight += 1
        try:
            await self.app(scope, receive, send)  # returns once the whole response (streaming too) has been sent
        finally:
            with cls._lock:
                cls.in_flight -= 1
                cls.last_seen = time.monotonic()


def busy() -> bool:
    """Is anything going on that exiting would cut short?"""
    from app.services import compute, pipeline

    return Activity.in_flight > 0 or pipeline.busy() or compute.heavy.length() > 0


def idle_for() -> float:
    return 0.0 if busy() else time.monotonic() - Activity.last_seen


def launchd_socket(name: str = "Listeners") -> socket.socket | None:
    """The listening socket launchd holds for us (the plist's Sockets/<name>), or None when not started that way."""
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    except OSError:
        return None
    fds, count = ctypes.POINTER(ctypes.c_int)(), ctypes.c_size_t(0)
    if libc.launch_activate_socket(name.encode(), ctypes.byref(fds), ctypes.byref(count)) != 0 or count.value == 0:
        return None
    fd = fds[0]
    libc.free(fds)
    return socket.socket(fileno=fd)


def _watch(server, idle: float, check: float) -> None:
    while not server.should_exit:
        time.sleep(check)
        if idle_for() > idle:
            log.warning("idle for %d minutes: exiting (launchd starts it again on the next visit)", idle // 60)
            server.should_exit = True


def main() -> None:
    import uvicorn

    sock = launchd_socket()
    options = dict(proxy_headers=True, forwarded_allow_ips="127.0.0.1", log_level="warning", access_log=False)
    if sock is None:
        uvicorn.run("app.main:app", host="127.0.0.1", port=8000, **options)
        return
    server = uvicorn.Server(uvicorn.Config("app.main:app", **options))
    threading.Thread(target=_watch, args=(server, IDLE_SECONDS, CHECK_SECONDS), name="idle-watch", daemon=True).start()
    log.warning("started on demand by launchd; exits after %d idle minutes", IDLE_SECONDS // 60)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
