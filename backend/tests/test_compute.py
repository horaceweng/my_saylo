import asyncio
import threading
import time

import pytest

from app.services import compute
from app.services.compute import Busy, HeavyLock


class Meter:
    """Counts how many jobs are inside the lock at once."""

    def __init__(self):
        self.now = self.peak = 0
        self.lock = threading.Lock()

    def enter(self):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)

    def leave(self):
        with self.lock:
            self.now -= 1


def test_jobs_in_threads_never_overlap():
    lock, meter = HeavyLock(), Meter()

    def job():
        with lock.hold("whisper"):
            meter.enter()
            time.sleep(0.02)
            meter.leave()

    threads = [threading.Thread(target=job) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert meter.peak == 1 and lock.length() == 0


async def test_async_and_thread_jobs_exclude_each_other():
    lock, meter = HeavyLock(), Meter()

    def in_thread():
        with lock.hold("whisper"):
            meter.enter()
            time.sleep(0.03)
            meter.leave()

    async def in_loop():
        async with lock.ahold("ollama"):
            meter.enter()
            await asyncio.sleep(0.03)
            meter.leave()

    await asyncio.gather(*[asyncio.to_thread(in_thread) for _ in range(3)], *[in_loop() for _ in range(3)])
    assert meter.peak == 1


def test_a_job_that_calls_something_wanting_the_lock_does_not_wait_for_itself():
    lock = HeavyLock()
    done = []

    def outer():
        with lock.hold("whisper"):
            with lock.hold("ollama"):  # e.g. transcribe → translate inside one job
                done.append("inner")
            done.append("outer")

    t = threading.Thread(target=outer)
    t.start()
    t.join(2)
    assert not t.is_alive() and done == ["inner", "outer"]


async def test_the_thread_a_job_starts_from_inherits_holding():
    lock = HeavyLock()

    async def run():
        async with lock.ahold("ollama"):
            await asyncio.wait_for(asyncio.to_thread(lambda: lock.hold("whisper").__enter__()), 2)  # would hang if it waited

    await asyncio.wait_for(run(), 3)


def test_waiting_too_long_raises_busy_and_leaves_the_line():
    lock = HeavyLock()
    release = threading.Event()
    started = threading.Event()

    def holder():
        with lock.hold("whisper"):
            started.set()
            release.wait(2)

    t = threading.Thread(target=holder)
    t.start()
    started.wait(2)
    with pytest.raises(Busy):
        with lock.hold("whisper", timeout=0.05):
            pass
    assert lock.length() == 1  # only the holder is left
    release.set()
    t.join()


async def test_a_waiter_hears_its_place_in_the_line():
    lock, seen = HeavyLock(), []
    release = threading.Event()
    started = threading.Event()

    def holder():
        with lock.hold("whisper"):
            started.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    started.wait(2)
    compute.on_wait.set(seen.append)

    async def waiter():
        async with lock.ahold("ollama"):
            return "ran"

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.2)
    assert seen == [1]  # one job (the holder) is ahead
    release.set()
    assert await asyncio.wait_for(task, 3) == "ran"
    t.join()


async def test_a_cancelled_waiter_does_not_block_the_next_one():
    lock = HeavyLock()
    release = threading.Event()
    started = threading.Event()

    def holder():
        with lock.hold("whisper"):
            started.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    started.wait(2)

    async def waiter():
        async with lock.ahold("ollama"):
            pass

    gone = asyncio.create_task(waiter())
    await asyncio.sleep(0.1)
    gone.cancel()
    with pytest.raises(asyncio.CancelledError):
        await gone
    assert lock.length() == 1
    release.set()
    t.join()
    async with lock.ahold("ollama"):  # the cancelled ticket must not have been handed the lock
        pass
    assert lock.length() == 0


def test_the_previous_kind_is_unloaded_before_another_runs():
    lock, unloaded = HeavyLock(), []
    lock.register_unloader("ollama", lambda: unloaded.append("ollama"))
    lock.register_unloader("whisper", lambda: unloaded.append("whisper"))
    with lock.hold("ollama"):
        pass
    with lock.hold("ollama"):
        pass
    assert unloaded == []
    with lock.hold("whisper"):
        pass
    assert unloaded == ["ollama"]
    with lock.hold("ollama"):
        pass
    assert unloaded == ["ollama", "whisper"]


def test_idle_clean_up_only_runs_when_nothing_else_wants_the_lock():
    lock, ran = HeavyLock(), []
    with lock.hold("whisper"):
        assert lock.run_if_idle("whisper", lambda: ran.append(1)) is False  # busy
    assert lock.run_if_idle("ollama", lambda: ran.append(2)) is False  # not the last kind
    assert lock.run_if_idle("whisper", lambda: ran.append(3)) is True and ran == [3]
    assert lock.run_if_idle("whisper", lambda: ran.append(4)) is False  # already released


def test_cooldown():
    c = compute.Cooldown(0.05)
    assert not c.active()
    c.start()
    assert c.active()
    time.sleep(0.06)
    assert not c.active()
