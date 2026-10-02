import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import engine, get_session
from app.deps import current_user
from app.models import User
from app.services import ai_cache, prompts, usage
from app.services.explain_queue import ExplainService
from app.services.llm import LLMError, chat_json, make_provider

router = APIRouter(prefix="/api/ai", tags=["ai"])

_service = ExplainService(engine)


def get_explain_service() -> ExplainService:
    return _service


class ExplainRequest(BaseModel):
    sentence: str = Field(min_length=1, max_length=1500)  # a sentence, or a whole paragraph of a book
    context: str = Field(default="", max_length=1200)


@router.post("/explain-sentence")
async def explain_sentence(body: ExplainRequest, session: Session = Depends(get_session), user: User = Depends(current_user)):
    provider = make_provider()

    async def ask():
        usage.charge_ai(session, user)  # only a real question counts; a cached answer does not reach this
        return await chat_json(provider, prompts.EXPLAIN_SYSTEM, prompts.explain_user_prompt(body.sentence, body.context), prompts.SentenceExplanation)

    try:
        return await ai_cache.cached(session, "explain", body.sentence, prompts.SentenceExplanation, ask)
    except LLMError as e:
        raise HTTPException(503, str(e)) from e


@router.post("/explain-sentence/stream")
async def explain_sentence_stream(
    body: ExplainRequest, service: ExplainService = Depends(get_explain_service), session: Session = Depends(get_session),
    user: User = Depends(current_user),
):
    """Newline-delimited JSON: {"type":"queued","position":N} while waiting for its turn, {"type":"partial","data":{…}}
    while generating, then "done" or "error"."""
    if service.cached(body.sentence) is None:
        usage.charge_ai(session, user)  # refused here, before the stream starts, so the page gets a plain 429

    async def lines():
        async for event in service.subscribe(body.sentence, body.context):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
