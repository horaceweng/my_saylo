import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel
from sqlmodel import Session

from app.config import settings
from app.models import AiCache

T = TypeVar("T", bound=BaseModel)


def cache_key(kind: str, payload: str) -> str:
    return hashlib.sha256(f"{kind}|{settings.active_llm_model}|{payload}".encode()).hexdigest()


async def cached(
    session: Session, kind: str, payload: str, schema: type[T], produce: Callable[[], Awaitable[T]]
) -> T:
    """Return the cached result for (kind, model, payload), computing and storing it on a miss."""
    key = cache_key(kind, payload)
    row = session.get(AiCache, key)
    if row is not None:
        return schema.model_validate(json.loads(row.payload_json))
    result = await produce()
    session.add(AiCache(key=key, kind=kind, payload_json=result.model_dump_json()))
    session.commit()
    return result
