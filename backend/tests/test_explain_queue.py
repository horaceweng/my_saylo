import asyncio
import json

import pytest
from sqlmodel import SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.services.explain_queue import ExplainService
from app.services.llm import LLMError


def answer(tag: str) -> str:
    return json.dumps({"translation": f"譯:{tag}", "structure": "S", "grammar_points": [{"point": "p", "explanation": "e"}] * 3,
                       "phrases": [], "similar_examples": [{"en": "x", "zh": "y"}]}, ensure_ascii=False)


class FakeProvider:
    """Streams a canned answer in small pieces. `gates[sentence]` pauses it after the first piece."""

    log: list[str] = []
    gates: dict[str, asyncio.Event] = {}
    fail: set[str] = set()
    bad_json: set[str] = set()

    @staticmethod
    def sentence_of(user: str) -> str:
        return user.split("句子：", 1)[1].split("\n", 1)[0]

    async def stream(self, system, user, *, json_mode=False):
        s = self.sentence_of(user)
        FakeProvider.log.append(s)
        if s in FakeProvider.fail:
            raise LLMError("boom")
        text = "not json" if s in FakeProvider.bad_json else answer(s)
        pieces = [text[i : i + 40] for i in range(0, len(text), 40)]
        for n, piece in enumerate(pieces):
            yield piece
            await asyncio.sleep(0)
            if n == 0 and s in FakeProvider.gates:
                await FakeProvider.gates[s].wait()

    async def chat(self, system, user, *, json_mode=False):
        FakeProvider.log.append("retry:" + self.sentence_of(user))
        return answer(self.sentence_of(user))


@pytest.fixture
def service():
    FakeProvider.log, FakeProvider.gates, FakeProvider.fail, FakeProvider.bad_json = [], {}, set(), set()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return ExplainService(engine, provider_factory=FakeProvider, throttle=0)


async def collect(gen):
    return [e async for e in gen]


async def settle(service, timeout=2.0):
    """Wait until the worker has nothing left to do."""
    async def wait():
        while service.jobs or service.current:
            await asyncio.sleep(0.005)
    await asyncio.wait_for(wait(), timeout)


async def test_streams_partials_then_done_and_caches(service):
    events = await collect(service.subscribe("A"))
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "done" and kinds.count("partial") >= 2
    assert events[-1]["data"]["translation"] == "譯:A"
    # partials grow: the last partial is not shorter than the first
    first, last = events[0]["data"], [e for e in events if e["type"] == "partial"][-1]["data"]
    assert len(json.dumps(last)) >= len(json.dumps(first))
    # second request is served from the cache without asking the model again
    FakeProvider.log.clear()
    again = await collect(service.subscribe("A"))
    assert [e["type"] for e in again] == ["done"] and FakeProvider.log == []


async def test_two_listeners_share_one_generation(service):
    a, b = await asyncio.gather(collect(service.subscribe("A")), collect(service.subscribe("A")))
    assert a[-1]["type"] == b[-1]["type"] == "done"
    assert FakeProvider.log == ["A"]


async def test_late_listener_gets_the_text_so_far(service):
    FakeProvider.gates["A"] = asyncio.Event()
    first = asyncio.create_task(collect(service.subscribe("A")))
    await asyncio.sleep(0.05)  # A has produced its first piece and is paused
    late = asyncio.create_task(collect(service.subscribe("A")))
    await asyncio.sleep(0.05)
    FakeProvider.gates["A"].set()
    r1, r2 = await asyncio.gather(first, late)
    assert r2[0]["type"] == "partial" and r2[-1]["type"] == "done" and r1[-1]["type"] == "done"
    assert FakeProvider.log == ["A"]


async def test_requests_for_different_sentences_run_one_at_a_time(service):
    FakeProvider.gates["A"] = asyncio.Event()
    first = asyncio.create_task(collect(service.subscribe("A")))
    await asyncio.sleep(0.05)
    second = asyncio.create_task(collect(service.subscribe("B")))
    await asyncio.sleep(0.05)
    assert service.current.sentence == "A" and [j.sentence for j in service.queue] == ["B"]
    assert FakeProvider.log == ["A"]  # B has not started yet
    FakeProvider.gates["A"].set()
    r1, r2 = await asyncio.gather(first, second)
    assert r1[-1]["type"] == r2[-1]["type"] == "done"
    assert FakeProvider.log == ["A", "B"]


async def test_errors_are_reported_and_do_not_stick(service):
    FakeProvider.fail.add("A")
    events = await collect(service.subscribe("A"))
    assert events[-1] == {"type": "error", "message": "boom"}
    assert "A" not in service.jobs
    FakeProvider.fail.clear()
    assert (await collect(service.subscribe("A")))[-1]["type"] == "done"


async def test_invalid_final_json_falls_back_to_a_retry(service):
    FakeProvider.bad_json.add("A")
    events = await collect(service.subscribe("A"))
    assert events[-1]["type"] == "done" and "retry:A" in FakeProvider.log


async def test_generation_stops_when_the_only_listener_leaves(service):
    FakeProvider.gates["A"] = asyncio.Event()  # A stalls after its first piece
    gen = service.subscribe("A")
    await asyncio.wait_for(gen.__anext__(), 2)  # first partial arrives
    assert service.current.sentence == "A"
    await gen.aclose()  # the learner closed the panel
    await settle(service)
    assert service.cached("A") is None  # cancelled, not silently finished
    assert "A" not in service.jobs and service.current is None


async def test_a_queued_request_is_dropped_when_its_listener_leaves(service):
    FakeProvider.gates["A"] = asyncio.Event()
    first = asyncio.create_task(collect(service.subscribe("A")))
    await asyncio.sleep(0.05)
    gen = service.subscribe("B")
    waiting = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.05)
    assert [j.sentence for j in service.queue] == ["B"]
    waiting.cancel()
    await asyncio.gather(waiting, return_exceptions=True)
    await gen.aclose()
    assert service.queue == [] and "B" not in service.jobs
    FakeProvider.gates["A"].set()
    await first
    assert "B" not in FakeProvider.log  # the model was never asked about B


async def test_generation_continues_while_at_least_one_listener_remains(service):
    FakeProvider.gates["A"] = asyncio.Event()
    stays = asyncio.create_task(collect(service.subscribe("A")))
    leaves = service.subscribe("A")
    await asyncio.wait_for(leaves.__anext__(), 2)
    await leaves.aclose()
    await asyncio.sleep(0.02)
    FakeProvider.gates["A"].set()
    events = await asyncio.wait_for(stays, 2)
    assert events[-1]["type"] == "done" and FakeProvider.log == ["A"]


async def test_no_background_work_without_a_request(service):
    await asyncio.sleep(0.05)
    assert FakeProvider.log == [] and service.jobs == {} and service.current is None


async def test_a_request_waiting_behind_another_is_told_its_place_in_line(service):
    FakeProvider.gates["A"] = asyncio.Event()
    first = asyncio.create_task(collect(service.subscribe("A")))
    await asyncio.sleep(0.05)
    second = asyncio.create_task(collect(service.subscribe("B")))
    third = asyncio.create_task(collect(service.subscribe("C")))
    await asyncio.sleep(0.05)
    FakeProvider.gates["A"].set()
    r1, r2, r3 = await asyncio.gather(first, second, third)
    assert [e for e in r1 if e["type"] == "queued"] == []  # the one running was never waiting
    assert [e for e in r2 if e["type"] == "queued"][0] == {"type": "queued", "position": 1}
    assert [e["position"] for e in r3 if e["type"] == "queued"] == [2, 1]  # moves up as the line shortens
    assert all(r[-1]["type"] == "done" for r in (r1, r2, r3))  # a queued event never ends the stream
    assert r2.index(next(e for e in r2 if e["type"] == "queued")) < r2.index(next(e for e in r2 if e["type"] == "partial"))


async def test_waiting_for_the_local_model_is_reported_as_queued_too(service, monkeypatch):
    import threading

    from app.services.compute import heavy

    class Local(FakeProvider):
        async def stream(self, system, user, *, json_mode=False):
            async with heavy.ahold("ollama"):
                async for piece in FakeProvider.stream(self, system, user, json_mode=json_mode):
                    yield piece

    service.provider_factory = Local
    release, started = threading.Event(), threading.Event()

    def other_job():  # e.g. whisper transcribing a video
        with heavy.hold("whisper"):
            started.set()
            release.wait(5)

    t = threading.Thread(target=other_job)
    t.start()
    started.wait(2)
    task = asyncio.create_task(collect(service.subscribe("A")))
    await asyncio.sleep(0.2)
    release.set()
    events = await asyncio.wait_for(task, 3)
    t.join()
    assert events[0] == {"type": "queued", "position": 1} and events[-1]["type"] == "done"
