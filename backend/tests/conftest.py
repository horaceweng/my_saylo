import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.db import get_session
from app.main import app


class FakeLLM:
    """Returns canned JSON keyed by a substring of the system prompt."""

    replies: dict[str, str] = {}
    calls = 0

    async def chat(self, system, user, *, json_mode=False):
        FakeLLM.calls += 1
        for marker, reply in FakeLLM.replies.items():
            if marker in system:
                return reply
        raise AssertionError(f"no canned reply for: {system[:40]}")


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def client(session, monkeypatch):
    app.dependency_overrides[get_session] = lambda: session
    FakeLLM.replies, FakeLLM.calls = {}, 0
    for module in ("ai", "dictionary"):
        monkeypatch.setattr(f"app.routers.{module}.make_provider", FakeLLM)
    yield TestClient(app)
    app.dependency_overrides.clear()
