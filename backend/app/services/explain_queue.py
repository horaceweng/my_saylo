"""Generates sentence explanations on request, streaming partial results to whoever is listening.

Only work the learner asked for is done: when the last listener of a job goes away (the panel was
closed, or they moved on to another sentence) generation stops right away instead of finishing
in the background. Requests are handled one at a time so the local model is never asked to do two
things at once, and a second request for a sentence that is already being written joins the same job.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.models import AiCache
from app.services import compute, prompts
from app.services.ai_cache import cache_key
from app.services.llm import LLMError, chat_json, make_provider
from app.services.partial_json import parse_partial

log = logging.getLogger(__name__)

Event = dict


@dataclass(eq=False)
class Job:
    sentence: str
    context: str
    text: str = ""
    finished: bool = False
    listeners: list[asyncio.Queue] = field(default_factory=list)
    task: asyncio.Task | None = None
    position: int = 0  # jobs ahead of this one, as last announced


class ExplainService:
    def __init__(self, engine: Engine, provider_factory: Callable = make_provider, throttle: float = 0.08):
        self.engine = engine
        self.provider_factory = provider_factory
        self.throttle = throttle
        self.jobs: dict[str, Job] = {}  # queued or running, by sentence
        self.queue: list[Job] = []
        self.current: Job | None = None
        self._drain: asyncio.Task | None = None

    # ---- cache ---------------------------------------------------------------------------

    def cached(self, sentence: str) -> prompts.SentenceExplanation | None:
        with Session(self.engine) as session:
            row = session.get(AiCache, cache_key("explain", sentence))
            return prompts.SentenceExplanation.model_validate(json.loads(row.payload_json)) if row else None

    def _store(self, sentence: str, result: prompts.SentenceExplanation) -> None:
        with Session(self.engine) as session:
            session.merge(AiCache(key=cache_key("explain", sentence), kind="explain", payload_json=result.model_dump_json()))
            session.commit()

    # ---- public API ----------------------------------------------------------------------

    async def subscribe(self, sentence: str, context: str = "") -> AsyncIterator[Event]:
        """Events for one request: {"type":"queued","position":N} while it waits for its turn (N jobs are ahead of it),
        zero or more {"type":"partial"}, then a "done" or "error"."""
        hit = self.cached(sentence)
        if hit:
            yield {"type": "done", "data": hit.model_dump()}
            return
        job = self.jobs.get(sentence) or self._enqueue(sentence, context)
        inbox: asyncio.Queue[Event] = asyncio.Queue()
        job.listeners.append(inbox)
        if job.position > 0:
            inbox.put_nowait({"type": "queued", "position": job.position})
        snapshot = parse_partial(job.text) if job.text else None
        if snapshot:  # joined a job that is already under way: catch up with what has been written
            inbox.put_nowait({"type": "partial", "data": snapshot})
        try:
            while True:
                event = await inbox.get()
                yield event
                if event["type"] not in ("partial", "queued"):
                    return
        finally:
            job.listeners.remove(inbox)
            if not job.listeners and not job.finished:
                self._abandon(job)

    # ---- internals -----------------------------------------------------------------------

    def _enqueue(self, sentence: str, context: str) -> Job:
        job = Job(sentence, context)
        self.jobs[sentence] = job
        self.queue.append(job)
        self._announce()
        if self._drain is None or self._drain.done():
            self._drain = asyncio.create_task(self._drain_loop())
        return job

    def _abandon(self, job: Job) -> None:
        """Nobody is waiting for this any more: drop it if queued, stop the model if running."""
        if job in self.queue:
            self.queue.remove(job)
            self.jobs.pop(job.sentence, None)
            job.finished = True
            self._announce()
        elif job.task:
            job.task.cancel()

    async def _drain_loop(self) -> None:
        while self.queue:
            job = self.queue.pop(0)
            self.current = job
            job.position = 0
            self._announce()
            job.task = asyncio.create_task(self._generate(job))
            try:
                await job.task
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise  # the loop itself is being shut down
            finally:
                self.current = None

    def _announce(self) -> None:
        """Tell each waiting request how many jobs are ahead of it (the running one counts)."""
        ahead = 1 if self.current else 0
        for i, job in enumerate(self.queue):
            if job.position != i + ahead:
                job.position = i + ahead
                self._emit(job, {"type": "queued", "position": job.position})

    def _emit(self, job: Job, event: Event) -> None:
        for inbox in job.listeners:
            inbox.put_nowait(event)

    def _finish(self, job: Job, event: Event) -> None:
        job.finished = True
        self.jobs.pop(job.sentence, None)
        self._emit(job, event)

    async def _generate(self, job: Job) -> None:
        provider = self.provider_factory()
        user = prompts.explain_user_prompt(job.sentence, job.context)
        # Waiting for the local model (whisper or another request is using it) is shown like waiting in line.
        compute.on_wait.set(lambda position: self._emit(job, {"type": "queued", "position": position}))
        try:
            last = 0.0
            async for chunk in provider.stream(prompts.EXPLAIN_SYSTEM, user, json_mode=True):
                job.text += chunk
                now = time.monotonic()
                if now - last >= self.throttle:
                    last = now
                    partial = parse_partial(job.text)
                    if partial is not None:
                        self._emit(job, {"type": "partial", "data": partial})
            try:
                result = prompts.SentenceExplanation.model_validate(json.loads(job.text))
            except (json.JSONDecodeError, ValidationError):
                result = await chat_json(provider, prompts.EXPLAIN_SYSTEM, user, prompts.SentenceExplanation)
            self._store(job.sentence, result)
            self._finish(job, {"type": "done", "data": result.model_dump()})
        except asyncio.CancelledError:
            self.jobs.pop(job.sentence, None)
            job.finished = True
            raise
        except LLMError as e:
            self._finish(job, {"type": "error", "message": str(e)})
        except Exception as e:  # noqa: BLE001 - a failed job must not kill the worker
            log.exception("explain job failed")
            self._finish(job, {"type": "error", "message": f"產生說明時發生錯誤：{e}"})
