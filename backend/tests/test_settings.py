import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.config import settings
from app.models import Setting
from app.services import app_settings

TAGS = {"models": [
    {"name": "qwen3.5:9b", "size": 6_600_000_000}, {"name": "gemma4:e4b", "size": 9_600_000_000},
    {"name": "nomic-embed-text:latest", "size": 274_000_000},
]}


@pytest.fixture
def env(client, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("app.routers.settings.engine", engine)
    monkeypatch.setattr(settings, "llm_model", "qwen3.5:9b")  # restored after the test
    monkeypatch.setattr(settings, "whisper_model", "mlx-community/whisper-large-v3-turbo")
    monkeypatch.setattr(app_settings, "installed_llm_models", lambda client=None: [
        {"name": "gemma4:e4b", "size_gb": 9.6}, {"name": "qwen3.5:9b", "size_gb": 6.6}])
    monkeypatch.setattr(app_settings, "whisper_downloaded", lambda repo: repo.endswith("turbo"))
    return client, engine


def test_settings_show_the_current_choices_and_what_is_available(env):
    client, _ = env
    body = client.get("/api/settings").json()
    assert body["llm_model"] == "qwen3.5:9b" and body["ollama_ok"] is True
    assert [m["name"] for m in body["llm_models"]] == ["gemma4:e4b", "qwen3.5:9b"]
    turbo = next(w for w in body["whisper_models"] if w["repo"].endswith("turbo"))
    assert turbo["downloaded"] is True and "預設" in turbo["label"]
    assert [w["downloaded"] for w in body["whisper_models"]].count(True) == 1


def test_a_new_model_is_saved_used_at_once_and_reloaded_at_the_next_start(env):
    client, engine = env
    body = client.put("/api/settings", json={"llm_model": "gemma4:e4b", "whisper_model": "mlx-community/whisper-small-mlx"}).json()
    assert body["llm_model"] == "gemma4:e4b" and settings.llm_model == "gemma4:e4b" and settings.whisper_model.endswith("small-mlx")
    with Session(engine) as s:
        assert s.get(Setting, "llm_model").value == "gemma4:e4b"
    settings.llm_model = settings.whisper_model = "changed-by-something-else"
    app_settings.load_overrides(engine)  # what happens when the server starts again
    assert settings.llm_model == "gemma4:e4b" and settings.whisper_model.endswith("small-mlx")


def test_an_llm_that_is_not_installed_is_refused_with_the_command_to_install_it(env):
    client, _ = env
    res = client.put("/api/settings", json={"llm_model": "llama3.1:8b"})
    assert res.status_code == 400 and "ollama pull llama3.1:8b" in res.json()["detail"]
    assert settings.llm_model == "qwen3.5:9b"


def test_without_ollama_the_llm_cannot_be_changed_but_the_page_still_loads(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(app_settings, "installed_llm_models", lambda client=None: None)
    assert client.get("/api/settings").json()["ollama_ok"] is False
    res = client.put("/api/settings", json={"llm_model": "gemma4:e4b"})
    assert res.status_code == 400 and "Ollama" in res.json()["detail"]
    assert client.put("/api/settings", json={"whisper_model": "mlx-community/whisper-small-mlx"}).status_code == 200  # unrelated to Ollama


def test_an_unknown_whisper_model_is_refused_and_nothing_changes_when_one_value_is_bad(env):
    client, engine = env
    assert client.put("/api/settings", json={"whisper_model": "someone/else"}).status_code == 400
    res = client.put("/api/settings", json={"llm_model": "gemma4:e4b", "whisper_model": "someone/else"})
    assert res.status_code == 400 and settings.llm_model == "qwen3.5:9b"  # the valid half was not applied either
    with Session(engine) as s:
        assert s.get(Setting, "llm_model") is None


def test_an_empty_update_changes_nothing(env):
    client, _ = env
    assert client.put("/api/settings", json={}).json()["llm_model"] == "qwen3.5:9b"


def test_installed_models_are_listed_without_embedding_models():
    def handler(request):
        return httpx.Response(200, json=TAGS)

    models = app_settings.installed_llm_models(httpx.Client(transport=httpx.MockTransport(handler)))
    assert models == [{"name": "gemma4:e4b", "size_gb": 9.6}, {"name": "qwen3.5:9b", "size_gb": 6.6}]

    def down(request):
        raise httpx.ConnectError("refused")

    assert app_settings.installed_llm_models(httpx.Client(transport=httpx.MockTransport(down))) is None
    assert app_settings.installed_llm_models(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))) is None


def test_health_says_what_is_missing(env, monkeypatch):
    client, _ = env
    body = client.get("/api/health").json()
    assert body["ok"] and body["ollama"] is True and body["llm_model_installed"] is True and "dict" in body and "ffmpeg" in body
    monkeypatch.setattr(settings, "llm_model", "not-installed:1b")
    assert client.get("/api/health").json()["llm_model_installed"] is False
    monkeypatch.setattr(app_settings, "installed_llm_models", lambda client=None: None)
    down = client.get("/api/health").json()
    assert down["ollama"] is False and down["llm_model_installed"] is False
