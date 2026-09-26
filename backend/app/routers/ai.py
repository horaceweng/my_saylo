import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import engine, get_session
from app.services import ai_cache, prompts
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
async def explain_sentence(body: ExplainRequest, session: Session = Depends(get_session)):
    provider = make_provider()
    try:
        return await ai_cache.cached(
            session, "explain", body.sentence, prompts.SentenceExplanation,
            lambda: chat_json(provider, prompts.EXPLAIN_SYSTEM, prompts.explain_user_prompt(body.sentence, body.context), prompts.SentenceExplanation),
        )
    except LLMError as e:
        raise HTTPException(503, str(e)) from e


@router.post("/explain-sentence/stream")
async def explain_sentence_stream(body: ExplainRequest, service: ExplainService = Depends(get_explain_service)):
    """Newline-delimited JSON: {"type":"partial","data":{…}} while generating, then "done" or "error"."""

    async def lines():
        async for event in service.subscribe(body.sentence, body.context):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
