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


async def test_the_real_call_sites_take_turns(monkeypatch):
    """Local whisper, an Ollama request and the local voice never run at the same time."""
    import sys
    import types

    import httpx
    import numpy as np

    from app.services import llm, transcribe, tts

    meter = Meter()

    def busy(result):
        meter.enter()
        time.sleep(0.05)
        meter.leave()
        return result

    fake_mlx = types.ModuleType("mlx_whisper")
    fake_mlx.transcribe = lambda audio, **kw: busy({"segments": []})
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake_mlx)
    monkeypatch.setattr(transcribe, "_schedule_idle_release", lambda: None)

    class FakeVoice:
        def generate(self, **kw):
            busy(None)
            return [types.SimpleNamespace(audio=np.zeros(10))]

    monkeypatch.setattr(tts, "_load_model", lambda: FakeVoice())

    real = httpx.AsyncClient

    def handler(request):
        busy(None)  # the model "thinks" while holding the lock (this handler runs on the event loop, like a slow reply)
        return httpx.Response(200, json={"message": {"content": "hi"}})

    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: None)
    voice = tts.VOICES[0]
    await asyncio.gather(
        asyncio.to_thread(transcribe.run_whisper, "a.wav"),
        asyncio.to_thread(transcribe.run_whisper, np.zeros(10)),
        asyncio.to_thread(tts.synthesize, "Hello", voice),
        llm.OllamaProvider(model="m").chat("s", "u"),
        llm.OllamaProvider(model="m").chat("s", "u"),
    )
    assert meter.peak == 1


async def test_a_cloud_call_does_not_wait_for_the_lock(monkeypatch):
    import httpx

    from app.config import settings
    from app.services import llm

    real = httpx.AsyncClient
    monkeypatch.setattr(settings, "cloud_base_url", "https://c.example/v1")
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "cloud"}}]})), **kw))
    async with compute.heavy.ahold("whisper"):  # a local job is running
        assert await asyncio.wait_for(llm.OpenAICompatProvider(model="m").chat("s", "u"), 1) == "cloud"
