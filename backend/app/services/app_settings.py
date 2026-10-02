"""Settings the learner can change while the app runs: which LLM and which whisper model to use.
They live in the database (table `setting`), are loaded into the `settings` object at start-up and
take effect the next time the model is called."""

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.engine import Engine
from sqlmodel import Session

from app.config import settings
from app.models import Setting

CLOUD_FIELDS = ("llm_backend", "cloud_base_url", "cloud_api_key", "cloud_model", "stt_backend", "stt_base_url", "stt_api_key", "stt_model")
CHANGEABLE = ("llm_model", "whisper_model", *CLOUD_FIELDS)
SECRETS = ("cloud_api_key", "stt_api_key")


@dataclass(frozen=True)
class WhisperChoice:
    repo: str
    label: str
    size: str
    note: str


WHISPER_CHOICES = [
    WhisperChoice("mlx-community/whisper-tiny-mlx", "tiny", "約 75 MB", "最快，準確度差，只適合測試"),
    WhisperChoice("mlx-community/whisper-base-mlx", "base", "約 140 MB", "很快，錯字偏多"),
    WhisperChoice("mlx-community/whisper-small-mlx", "small", "約 460 MB", "快，一般清晰的錄音夠用"),
    WhisperChoice("mlx-community/whisper-medium-mlx", "medium", "約 1.5 GB", "較準，速度中等"),
    WhisperChoice("mlx-community/whisper-large-v3-turbo", "large-v3-turbo（預設）", "約 1.6 GB", "準確又快，建議使用"),
    WhisperChoice("mlx-community/whisper-large-v3", "large-v3", "約 3 GB", "最準，但明顯較慢"),
]


@dataclass(frozen=True)
class CloudPreset:
    id: str
    label: str
    base_url: str
    model: str
    note: str


# Prices as published in September 2026: check the provider's page, they change.
LLM_PRESETS = [
    CloudPreset("gemini", "Google Gemini（便宜，推薦）", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.1-flash-lite",
                "每百萬字元（token）輸入 $0.25、輸出 $1.50；有免費額度，但免費額度的內容可能被 Google 用來改進產品"),
    CloudPreset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-5-mini", "輸入 $0.25、輸出 $2.00；更便宜的是 gpt-5-nano（$0.05／$0.40）"),
    CloudPreset("opencode", "OpenCode Zen（免費模型，會輪替；輸入可能被拿去訓練）", "https://opencode.ai/zen/v1", "",
                "OpenAI 相容。免費模型是限時提供、會更換，模型名稱要自己填（到 opencode.ai 查目前有哪些免費模型）；"
                "多數免費模型的輸入可能被拿去訓練，Space Bunny、LongCat 標示 zero-retention。失敗時會自動改用本地模型（見下方開關）"),
    CloudPreset("openrouter", "OpenRouter（一把金鑰用很多模型）", "https://openrouter.ai/api/v1", "", "模型名稱要自己填，例如 anthropic/claude-haiku-4.5"),
    CloudPreset("custom", "其他（OpenAI 相容的服務）", "", "", "DeepSeek、Together、自己的伺服器等，填 Base URL 與模型名稱"),
]
STT_PRESETS = [
    CloudPreset("groq", "Groq Whisper（很便宜很快，推薦）", "https://api.groq.com/openai/v1", "whisper-large-v3-turbo",
                "每小時音訊 $0.04，一小時約 15 秒轉完；每個請求至少計 10 秒"),
    CloudPreset("openai", "OpenAI Whisper", "https://api.openai.com/v1", "whisper-1", "每小時音訊 $0.36"),
    CloudPreset("custom", "其他（OpenAI 相容的服務）", "", "", "填 Base URL 與模型名稱"),
]


class SettingError(ValueError):
    """A value the learner chose cannot be used; the message says what to do."""


def load_overrides(engine: Engine) -> None:
    """Put the saved choices into the live settings (called once at start-up)."""
    with Session(engine) as session:
        for key in CHANGEABLE:
            row = session.get(Setting, key)
            if row and row.value:
                setattr(settings, key, row.value)
        row = session.get(Setting, "fallback_local")
        if row and row.value:
            settings.fallback_local = row.value == "1"


def installed_llm_models(client: httpx.Client | None = None) -> list[dict] | None:
    """Models Ollama has: [{name, size_gb}], or None when Ollama cannot be reached."""
    own = client is None
    client = client or httpx.Client(timeout=2.5)
    try:
        resp = client.get(f"{settings.ollama_base_url}/api/tags")
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if own:
            client.close()
    return sorted(
        ({"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1)} for m in models if "embed" not in m["name"]),
        key=lambda m: m["name"],
    )


def whisper_downloaded(repo: str) -> bool:
    from huggingface_hub.constants import HF_HUB_CACHE

    return (Path(HF_HUB_CACHE) / f"models--{repo.replace('/', '--')}").exists()


def mask(secret: str) -> str:
    """A key as the page may show it: only the last four characters (nothing at all of a short key)."""
    if not secret:
        return ""
    return "••••" + secret[-4:] if len(secret) >= 12 else "••••"


def _preset_out(p: CloudPreset) -> dict:
    return {"id": p.id, "label": p.label, "base_url": p.base_url, "model": p.model, "note": p.note}


def snapshot() -> dict:
    """Everything the settings page shows. API keys are never sent, only whether one is set and its last characters."""
    models = installed_llm_models()
    return {
        "llm_model": settings.llm_model,
        "whisper_model": settings.whisper_model,
        "llm_backend": settings.llm_backend,
        "cloud_base_url": settings.cloud_base_url,
        "cloud_model": settings.cloud_model,
        "cloud_key": mask(settings.cloud_api_key),
        "stt_backend": settings.stt_backend,
        "stt_base_url": settings.stt_base_url,
        "stt_model": settings.stt_model,
        "stt_key": mask(settings.stt_api_key),
        "fallback_local": settings.fallback_local,
        "llm_presets": [_preset_out(p) for p in LLM_PRESETS],
        "stt_presets": [_preset_out(p) for p in STT_PRESETS],
        "ollama_ok": models is not None,
        "llm_models": models or [],
        "whisper_models": [
            {"repo": c.repo, "label": c.label, "size": c.size, "note": c.note, "downloaded": whisper_downloaded(c.repo)}
            for c in WHISPER_CHOICES
        ],
    }


def _is_local_address(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def _check_cloud(values: dict[str, str]) -> None:
    """Refuse a combination that cannot work, saying what is missing."""
    if values["llm_backend"] not in ("ollama", "cloud"):
        raise SettingError("不支援這個 AI 來源")
    if values["stt_backend"] not in ("local", "cloud"):
        raise SettingError("不支援這個語音辨識來源")
    for label, backend, url, model, key in (
        ("語言模型", values["llm_backend"] == "cloud", values["cloud_base_url"], values["cloud_model"], values["cloud_api_key"]),
        ("語音辨識", values["stt_backend"] == "cloud", values["stt_base_url"], values["stt_model"], values["stt_api_key"]),
    ):
        if url and urlparse(url).scheme not in ("http", "https"):
            raise SettingError(f"{label}的 Base URL 要以 http:// 或 https:// 開頭")
        if not backend:
            continue
        if not url:
            raise SettingError(f"請填寫{label}雲端服務的 Base URL")
        if not model:
            raise SettingError(f"請填寫{label}要用的模型名稱")
        if not key and not _is_local_address(url):
            raise SettingError(f"請填寫{label}雲端服務的 API 金鑰")


def update(
    engine: Engine, llm_model: str | None = None, whisper_model: str | None = None, cloud: dict[str, str | None] | None = None,
    fallback_local: bool | None = None,
) -> None:
    """Validate and save the new choices. Nothing is changed unless every given value is valid.
    `cloud` holds any of CLOUD_FIELDS; a missing or None field stays as it is (an empty key clears it)."""
    changes: dict[str, str] = {}
    if llm_model is not None:
        models = installed_llm_models()
        if models is None:
            raise SettingError("連不上 Ollama，無法確認這個模型是否已安裝。請先啟動 Ollama")
        if llm_model not in {m["name"] for m in models}:
            raise SettingError(f"Ollama 還沒有安裝「{llm_model}」，請先在終端機執行：ollama pull {llm_model}")
        changes["llm_model"] = llm_model
    if whisper_model is not None:
        if whisper_model not in {c.repo for c in WHISPER_CHOICES}:
            raise SettingError("不支援這個語音辨識模型")
        changes["whisper_model"] = whisper_model
    if cloud:
        merged = {f: getattr(settings, f) for f in CLOUD_FIELDS}
        for field, value in cloud.items():
            if field in CLOUD_FIELDS and value is not None:
                merged[field] = value.strip()
        _check_cloud(merged)
        changes.update({f: v for f, v in merged.items() if v != getattr(settings, f)})
    with Session(engine) as session:
        for key, value in changes.items():
            session.merge(Setting(key=key, value=value))
        if fallback_local is not None:
            session.merge(Setting(key="fallback_local", value="1" if fallback_local else "0"))
        session.commit()
    for key, value in changes.items():
        setattr(settings, key, value)
    if fallback_local is not None:
        settings.fallback_local = fallback_local


async def check_llm() -> dict:
    """Try the chosen language model with a tiny question."""
    from app.services.llm import LLMError, make_provider

    started = time.monotonic()
    try:
        provider = make_provider()
        provider = getattr(provider, "primary", provider)  # the test is about the chosen service, not the local safety net
        reply = await provider.chat("Answer with one word.", "Say OK.")
    except LLMError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": f"連線成功（{settings.active_llm_model}，回覆「{reply.strip()[:30]}」，{time.monotonic() - started:.1f} 秒）"}


def check_stt() -> dict:
    """Is the cloud recogniser reachable with this key? (Listing the models needs no audio.)"""
    if settings.stt_backend != "cloud":
        return {"ok": True, "message": "目前使用這台電腦上的 Whisper，不需要連線"}
    url = f"{settings.stt_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"} if settings.stt_api_key else {}
    try:
        resp = httpx.get(url, headers=headers, timeout=15)
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"連不上語音辨識服務：{type(e).__name__}"}
    if resp.status_code in (401, 403):
        return {"ok": False, "message": f"語音辨識服務拒絕了 API 金鑰（HTTP {resp.status_code}）"}
    if resp.status_code >= 400:
        return {"ok": False, "message": f"語音辨識服務回報錯誤（HTTP {resp.status_code}），請檢查 Base URL"}
    return {"ok": True, "message": f"連線成功，金鑰有效（模型 {settings.stt_model}）"}
