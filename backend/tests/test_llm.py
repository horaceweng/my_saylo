import pytest
from pydantic import BaseModel

from app.services.llm import LLMError, chat_json


class Answer(BaseModel):
    value: int


class FakeProvider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, system, user, *, json_mode=False):
        self.calls += 1
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_parses_fenced_json():
    p = FakeProvider(['```json\n{"value": 3}\n```'])
    assert (await chat_json(p, "s", "u", Answer)).value == 3


@pytest.mark.asyncio
async def test_retries_once_on_bad_output():
    p = FakeProvider(["not json", '{"value": 7}'])
    assert (await chat_json(p, "s", "u", Answer)).value == 7
    assert p.calls == 2


@pytest.mark.asyncio
async def test_gives_up_after_second_failure():
    p = FakeProvider(["nope", "still nope"])
    with pytest.raises(LLMError):
        await chat_json(p, "s", "u", Answer)
