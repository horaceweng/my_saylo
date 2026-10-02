import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import get_session
from app.deps import current_user
from app.models import AiCache, User
from app.services import ai_cache, dictionary, prompts, usage
from app.services.llm import LLMError, chat_json, make_provider
from app.services.partial_json import parse_partial

router = APIRouter(prefix="/api/dictionary", tags=["dictionary"])


class LevelsRequest(BaseModel):
    words: list[str] = Field(max_length=4000)


@router.post("/levels")
def word_levels(body: LevelsRequest):
    """Difficulty level (0 basic … 4 GRE/rare) of many words at once, for colouring a text.
    Inflected forms count as their base word; words the dictionary does not know are left out."""
    levels: dict[str, int] = {}
    for raw in dict.fromkeys(w.strip().lower() for w in body.words):
        if not _WORD_RE.match(raw):
            continue
        entry = dictionary.lookup(raw)
        parts = [dictionary.lookup(part) for part in raw.split("-")] if "-" in raw else []
        if "-" in raw and all(parts) and (entry is None or (not entry.tags and not entry.frq and not entry.bnc)):
            levels[raw] = max(part.level for part in parts)  # "four-year": as hard as its hardest part
        elif entry is not None:
            levels[raw] = entry.level
    return {"levels": levels}

_WORD_RE = re.compile(r"^[a-zA-Z][a-zA-Z'-]{0,40}$")


@router.get("/root/{root}")
async def words_with_root(root: str, meaning: str = "", session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Words sharing a root. The LLM proposes them, ECDICT filters out invented ones."""
    root = root.strip().lower()
    if not _WORD_RE.match(root):
        raise HTTPException(400, "字根格式不正確")
    # Small models often drop a silent "e" (spicy → "spic"); prefer the real word if it exists.
    if dictionary.exists(root + "e") and dictionary.frequency_rank(root + "e") < dictionary.frequency_rank(root):
        root += "e"
    stem = root[:-1] if root.endswith("e") and len(root) > 3 else root
    provider = make_provider()

    async def ask():
        usage.charge_ai(session, user)
        return await chat_json(provider, prompts.ROOT_SYSTEM, f"字根：{root}" + (f"（{meaning}）" if meaning else ""), prompts.RootWords)

    try:
        proposed = await ai_cache.cached(session, "root", f"{root}|{meaning}", prompts.RootWords, ask)
    except LLMError as e:
        raise HTTPException(503, str(e)) from e
    words = []
    for w in dict.fromkeys(x.strip().lower() for x in proposed.words):
        # The LLM sometimes lists words of a different root; the spelling must contain this one.
        if stem not in w:
            continue
        entry = dictionary.lookup(w) if _WORD_RE.match(w) else None
        if entry and entry.word == w:
            words.append({"word": entry.word, "translation": entry.translation.split("\n")[0], "level": entry.level})
    return {"root": root, "words": words}


def get_word_provider():
    return make_provider()


@router.get("/{word}")
async def get_word(word: str, session: Session = Depends(get_session)):
    """The dictionary entry, at once. The AI's extra explanation is only included when it was made before;
    otherwise the page asks for it separately (…/enrich/stream) and shows it as it is written."""
    word = word.strip().lower()
    if not _WORD_RE.match(word):
        raise HTTPException(400, "不是有效的英文單字")
    entry = dictionary.lookup(word)
    target = entry.word if entry else word
    row = session.get(AiCache, ai_cache.cache_key("word", target))
    result: dict = {
        "query": word, "found": entry is not None, "target": target,
        "ai": json.loads(row.payload_json) if row else None, "ai_error": None,
    }
    if entry:
        result["entry"] = {
            "word": entry.word,
            "phonetic": entry.phonetic,
            "translation": entry.translation,
            "pos": entry.pos,
            "tags": entry.tags,
            "level": entry.level,
            "level_label": dictionary.LEVEL_LABELS[entry.level],
            "forms": entry.exchange,
            "is_inflection": entry.word != word,
        }
    return result


@router.post("/{word}/enrich/stream")
async def enrich_word(word: str, session: Session = Depends(get_session), provider=Depends(get_word_provider), user: User = Depends(current_user)):
    """The AI's extra explanation of a word (English meaning, examples, prefix/root/suffix, synonyms), streamed
    as newline-delimited JSON: {"type":"partial","data":{…}} … then "done" or "error". Kept for next time."""
    word = word.strip().lower()
    if not _WORD_RE.match(word):
        raise HTTPException(400, "不是有效的英文單字")
    entry = dictionary.lookup(word)
    target = entry.word if entry else word
    key, bind = ai_cache.cache_key("word", target), session.get_bind()
    cached = session.get(AiCache, key)
    saved = json.loads(cached.payload_json) if cached else None
    if saved is None:
        usage.charge_ai(session, user)

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    async def events():
        if saved is not None:
            yield line({"type": "done", "data": saved})
            return
        text, last = "", 0.0
        try:
            async for chunk in provider.stream(prompts.WORD_SYSTEM, f"單字：{target}", json_mode=True):
                text += chunk
                if time.monotonic() - last >= 0.08:
                    last = time.monotonic()
                    partial = parse_partial(text)
                    if partial is not None:
                        yield line({"type": "partial", "data": partial})
            try:
                result = prompts.WordEnrichment.model_validate(json.loads(text))
            except ValueError:
                result = await chat_json(provider, prompts.WORD_SYSTEM, f"單字：{target}", prompts.WordEnrichment)
        except LLMError as e:
            yield line({"type": "error", "message": str(e)})
            return
        with Session(bind) as s:
            s.merge(AiCache(key=key, kind="word", payload_json=result.model_dump_json()))
            s.commit()
        yield line({"type": "done", "data": result.model_dump()})

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
