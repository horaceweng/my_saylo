import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app import db
from app.config import settings
from app.db import get_session
from app.main import app
from app.models import User
from app.services import auth, compute, llm, ratelimit, transcribe


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


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Nothing a test does may reach the real database (fallback events are written through `db.engine`),
    and the in-memory counters start from zero."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    ratelimit.reset()
    llm.cloud_cooldown.reset()
    transcribe.cloud_cooldown.reset()
    compute.heavy._last_kind = None


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def fake_llm():
    return FakeLLM


PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def plain_http_cookies(monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", False)  # the test client talks http


@pytest.fixture
def make_client(session, monkeypatch):
    """Build a client for one user: `make_client("bob")` creates the account (once) and logs in; no name = not logged in."""
    app.dependency_overrides[get_session] = lambda: session
    FakeLLM.replies, FakeLLM.calls = {}, 0
    for module in ("ai", "dictionary"):
        monkeypatch.setattr(f"app.routers.{module}.make_provider", FakeLLM)

    def build(username: str | None = None, admin: bool = False) -> TestClient:
        c = TestClient(app)
        if username:
            if not session.exec(select(User).where(User.username == username)).first():
                auth.create_user(session, username, PASSWORD, is_admin=admin)
            assert c.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
        return c

    yield build
    app.dependency_overrides.clear()


@pytest.fixture
def client(make_client):
    """Logged in as an admin, so the existing tests keep seeing everything."""
    return make_client("admin", admin=True)


@pytest.fixture
def user_client(make_client):
    return make_client("alice")


@pytest.fixture
def other_client(make_client):
    return make_client("bob")


@pytest.fixture
def anon_client(make_client):
    return make_client()
