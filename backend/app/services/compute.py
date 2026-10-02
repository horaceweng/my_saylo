"""One heavy local model at a time.

The Mac mini has 16 GB: qwen3:8b (about 5.6 GB) and whisper large-v3-turbo together push it into swap (measured, see
PLAN-public.md Phase 0.1). So local whisper, Ollama and the local read-aloud voice take turns on a single process-wide
lock, and a model that is not the next one is unloaded first. Cloud calls never touch this lock.

The lock is taken at the lowest level, right around the model call (`OllamaProvider`, `transcribe.run_whisper`,
`tts.synthesize`), never around a whole job, so a media job that alternates between transcribing and translating lets
other work in between. Code that already holds the lock and calls something else that wants it (a context variable
marks the holder, in threads and in async tasks alike) just carries on instead of waiting for itself.

Waiters are served in order. A waiter can be told its place in the line (`on_wait`), which the explain panel shows.
"""

import asyncio
import contextvars
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager

log = logging.getLogger("uvicorn.error")


class Busy(TimeoutError):
    """Waited too long for the lock."""


class _Gone(Exception):
    """The one waiting stopped waiting (its request was cancelled)."""


_holding: contextvars.ContextVar[bool] = contextvars.ContextVar("heavy_lock_holding", default=False)
# Set by a caller that wants to hear its place in the line while it waits: callback(position), 0 = next.
on_wait: contextvars.ContextVar[Callable[[int], None] | None] = contextvars.ContextVar("heavy_lock_on_wait", default=None)

# Waiting for the lock blocks a thread; these threads are only for that, so a long line cannot starve the default pool.
_waiters = ThreadPoolExecutor(max_workers=64, thread_name_prefix="heavy-wait")


class _Ticket:
    __slots__ = ("gone",)

    def __init__(self) -> None:
        self.gone = False


class HeavyLock:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._line: deque[_Ticket] = deque()
        self._holder: _Ticket | None = None
        self._last_kind: str | None = None  # whose model may still be in memory
        self._unloaders: dict[str, Callable[[], None]] = {}

    # -- bookkeeping -----------------------------------------------------------------------------

    def register_unloader(self, kind: str, unload: Callable[[], None]) -> None:
        """`unload()` frees the memory of that kind's model; called (under the lock) when another kind is next."""
        self._unloaders[kind] = unload

    def length(self) -> int:
        """How many are running or waiting."""
        with self._cond:
            return len(self._line) + (1 if self._holder else 0)

    def _position(self, ticket: _Ticket) -> int:
        with self._cond:
            try:
                return list(self._line).index(ticket) + (1 if self._holder else 0)
            except ValueError:
                return 0

    def _enqueue(self) -> _Ticket:
        ticket = _Ticket()
        with self._cond:
            self._line.append(ticket)
        return ticket

    def _wait(self, ticket: _Ticket, timeout: float | None) -> None:
        deadline = None if timeout is None else _now() + timeout
        with self._cond:
            while True:
                if ticket.gone:
                    self._drop(ticket)
                    raise _Gone()
                if self._holder is None and self._line[0] is ticket:
                    self._line.popleft()
                    self._holder = ticket
                    return
                remaining = None if deadline is None else deadline - _now()
                if remaining is not None and remaining <= 0:
                    self._drop(ticket)
                    raise Busy("本地模型正忙")
                self._cond.wait(remaining)

    def _drop(self, ticket: _Ticket) -> None:
        try:
            self._line.remove(ticket)
        except ValueError:
            pass
        self._cond.notify_all()

    def _release(self, ticket: _Ticket) -> None:
        with self._cond:
            if self._holder is ticket:
                self._holder = None
            self._cond.notify_all()

    def _abandon(self, ticket: _Ticket) -> None:
        """The waiter gave up: leave the line, or let go if the lock had just been handed over."""
        with self._cond:
            ticket.gone = True
            if self._holder is ticket:
                self._holder = None
            self._drop(ticket)

    def _switch_to(self, kind: str) -> None:
        if self._last_kind and self._last_kind != kind:
            unload = self._unloaders.get(self._last_kind)
            if unload:
                try:
                    unload()
                except Exception:  # noqa: BLE001 - freeing memory is best effort
                    log.warning("could not unload the %s model", self._last_kind, exc_info=True)
        self._last_kind = kind

    # -- using it --------------------------------------------------------------------------------

    @contextmanager
    def hold(self, kind: str, timeout: float | None = None):
        """For code in a thread. Raises `Busy` when `timeout` seconds pass without getting its turn."""
        if _holding.get():
            yield
            return
        ticket = self._enqueue()
        self._wait(ticket, timeout)
        _holding.set(True)
        try:
            self._switch_to(kind)
            yield
        finally:
            _holding.set(False)
            self._release(ticket)

    @asynccontextmanager
    async def ahold(self, kind: str):
        """For async code: waits without blocking the event loop, and reports its place in the line to `on_wait`."""
        if _holding.get():
            yield
            return
        ticket = self._enqueue()
        waiting = asyncio.get_running_loop().run_in_executor(_waiters, self._wait, ticket, None)
        waiting.add_done_callback(lambda f: f.cancelled() or f.exception())  # an abandoned wait's error is not news
        notify, last = on_wait.get(), None
        try:
            while not waiting.done():
                position = self._position(ticket)
                if notify and position != last and position > 0:
                    last = position
                    notify(position)
                await asyncio.wait({waiting}, timeout=0.5)
            await waiting
        except BaseException:
            self._abandon(ticket)
            raise
        _holding.set(True)
        try:
            if self._last_kind != kind:
                await asyncio.to_thread(self._switch_to, kind)  # unloading can take seconds: not on the event loop
            yield
        finally:
            _holding.set(False)
            self._release(ticket)

    def run_if_idle(self, kind: str, fn: Callable[[], None]) -> bool:
        """Run `fn` only when nobody holds or awaits the lock and `kind` was the last model used (idle clean-up)."""
        with self._cond:
            if self._holder is not None or self._line or self._last_kind != kind:
                return False
            self._holder = ticket = _Ticket()
        try:
            fn()
            with self._cond:
                self._last_kind = None
        finally:
            self._release(ticket)
        return True


def _now() -> float:
    return time.monotonic()


heavy = HeavyLock()


class Cooldown:
    """After the cloud failed, skip it for a while instead of making every request wait for the same failure."""

    def __init__(self, seconds: float = 60.0) -> None:
        self.seconds = seconds
        self._until = 0.0

    def start(self) -> None:
        self._until = time.monotonic() + self.seconds

    def active(self) -> bool:
        return time.monotonic() < self._until

    def reset(self) -> None:
        self._until = 0.0
