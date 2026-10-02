import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.services import usage
from app.services.compute import Cooldown, heavy

log = logging.getLogger("uvicorn.error")

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    async def chat(self, system: str, user: str, *, json_mode: bool = False) -> str: ...


class OllamaProvider:
    """Talks to Ollama's native /api/chat.

    The OpenAI-compatible /v1 endpoint ignores `think: false`, which leaves the model
    reasoning for minutes; the native endpoint honours it.
    """

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.llm_model

    def _payload(self, system: str, user: str, json_mode: bool, stream: bool) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": stream,
            "think": False,
            "options": {"temperature": 0.3},
            # Do not keep the model (5.6 GB for qwen3:8b) in memory for the default five minutes.
            "keep_alive": f"{settings.local_keep_alive_seconds}s",
        }
        if json_mode:
            payload["format"] = "json"
        return payload

    async def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        payload = self._payload(system, user, json_mode, stream=False)
        async with heavy.ahold("ollama"):  # only one heavy local model runs at a time; waiting does not count as the model's time
            _loaded.add((self.base_url, self.model))
            try:
                async with asyncio.timeout(settings.llm_request_seconds):
                    async with httpx.AsyncClient(timeout=settings.llm_request_seconds) as client:
                        resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                        resp.raise_for_status()
            except httpx.ConnectError as e:
                raise LLMError("無法連線到 Ollama，請確認已執行 `ollama serve`") from e
            except TimeoutError as e:
                raise LLMError(f"本地模型超過 {settings.llm_request_seconds} 秒沒有回應") from e
            except httpx.HTTPError as e:
                raise LLMError(f"Ollama 請求失敗：{e}") from e
        return resp.json()["message"]["content"]

    async def stream(self, system: str, user: str, *, json_mode: bool = False) -> AsyncIterator[str]:
        """Yield the reply in pieces as the model produces it. Closing the iterator stops generation."""
        payload = self._payload(system, user, json_mode, stream=True)
        async with heavy.ahold("ollama"):
            _loaded.add((self.base_url, self.model))
            deadline = time.monotonic() + settings.llm_request_seconds
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_request_seconds, connect=10)) as client:
                    async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if time.monotonic() > deadline:
                                raise LLMError(f"本地模型超過 {settings.llm_request_seconds} 秒還沒寫完")
                            if not line.strip():
                                continue
                            event = json.loads(line)
                            chunk = event.get("message", {}).get("content", "")
                            if chunk:
                                yield chunk
                            if event.get("done"):
                                return
            except httpx.ConnectError as e:
                raise LLMError("無法連線到 Ollama，請確認已執行 `ollama serve`") from e
            except httpx.HTTPError as e:
                raise LLMError(f"Ollama 請求失敗：{e}") from e


# Ollama models this process has used since they were last unloaded: (base url, model).
_loaded: set[tuple[str, str]] = set()


def unload_ollama() -> None:
    """Ask Ollama to drop the models we used from memory now (`keep_alive: 0`), before whisper or the voice needs the RAM."""
    while _loaded:
        base_url, model = _loaded.pop()
        try:
            httpx.post(f"{base_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
        except httpx.HTTPError:
            log.debug("could not ask Ollama to unload %s", model)


heavy.register_unloader("ollama", unload_ollama)


def _http_message(response: httpx.Response) -> str:
    """What a cloud service's error means for the learner (never includes the key)."""
    code = response.status_code
    try:
        detail = response.json()["error"]["message"]
    except Exception:  # noqa: BLE001 - the body may be anything
        detail = response.text
    detail = str(detail).strip().replace("\n", " ")[:200]
    if code in (401, 403):
        return f"雲端服務拒絕了 API 金鑰（HTTP {code}）：請到「設定」檢查金鑰是否正確、有沒有開通"
    if code == 404:
        return "雲端服務找不到這個模型或網址：請到「設定」檢查 Base URL 與模型名稱"
    if code == 402:
        return "雲端帳戶的額度不足：請儲值，或換一個服務"
    if code == 429:
        return "雲端服務的速率或額度已達上限：請稍後再試，或檢查方案的額度"
    if code >= 500:
        return f"雲端服務暫時出錯（HTTP {code}），請稍後再試"
    return f"雲端服務回報錯誤（HTTP {code}）：{detail}"


class OpenAICompatProvider:
    """Any cloud service with the OpenAI chat API: Gemini, OpenAI, OpenRouter, Groq …

    JSON mode is asked for with `response_format`; a service that rejects it (HTTP 400) is asked again
    without, and the answer is validated afterwards like any other."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url if base_url is not None else settings.cloud_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.cloud_api_key
        self.model = model or settings.cloud_model

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _payload(self, system: str, user: str, json_mode: bool, stream: bool) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        url = f"{self.base_url}/chat/completions"
        try:
            async with asyncio.timeout(settings.llm_request_seconds):
                async with httpx.AsyncClient(timeout=settings.llm_request_seconds) as client:
                    resp = await client.post(url, json=self._payload(system, user, json_mode, False), headers=self._headers())
                    if resp.status_code == 400 and json_mode:
                        resp = await client.post(url, json=self._payload(system, user, False, False), headers=self._headers())
        except TimeoutError as e:
            raise LLMError(f"雲端服務超過 {settings.llm_request_seconds} 秒沒有回應") from e
        except httpx.HTTPError as e:
            raise LLMError(f"連不上雲端服務：{type(e).__name__}") from e
        if resp.status_code >= 400:
            raise LLMError(_http_message(resp))
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise LLMError("雲端服務的回覆格式不對，請確認 Base URL 是 OpenAI 相容的網址") from e
        if not content:
            raise LLMError("雲端模型沒有回覆內容，請換一個模型試試")
        return content

    async def stream(self, system: str, user: str, *, json_mode: bool = False) -> AsyncIterator[str]:
        """Yield the reply in pieces as it is produced. Closing the iterator ends the request."""
        url = f"{self.base_url}/chat/completions"
        deadline = time.monotonic() + settings.llm_request_seconds
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(settings.llm_request_seconds, connect=10)) as client:
                for with_format in ((True, False) if json_mode else (False,)):
                    async with client.stream("POST", url, json=self._payload(system, user, with_format, True), headers=self._headers()) as resp:
                        if resp.status_code == 400 and with_format:
                            await resp.aread()
                            continue  # this service does not take response_format: ask again without
                        if resp.status_code >= 400:
                            await resp.aread()
                            raise LLMError(_http_message(resp))
                        async for line in resp.aiter_lines():
                            if time.monotonic() > deadline:
                                raise LLMError(f"雲端服務超過 {settings.llm_request_seconds} 秒還沒寫完")
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)["choices"][0].get("delta", {}).get("content")
                            except (ValueError, KeyError, IndexError):
                                continue
                            if chunk:
                                yield chunk
                        return
        except httpx.HTTPError as e:
            raise LLMError(f"連不上雲端服務：{type(e).__name__}") from e


# After a cloud failure the cloud is skipped for a minute, so each request does not wait for the same timeout again.
cloud_cooldown = Cooldown(60.0)


class FallbackProvider:
    """The cloud service first; when it fails (unreachable, timeout, 429, 5xx, answers that are not usable JSON)
    the same request is answered by the local Ollama model instead. Every fallback is logged and counted
    (`UsageEvent` fallback_llm) so the admin page can show how often it happens."""

    def __init__(self, primary: LLMProvider, local_factory=None):
        self.primary = primary
        self._local_factory = local_factory or OllamaProvider
        self.fell_back = False

    def _fall_back(self, reason: object, cool_down: bool) -> LLMProvider:
        self.fell_back = True
        if cool_down:
            cloud_cooldown.start()
        log.warning("cloud LLM failed (%s); answering with the local model instead", reason)
        usage.record_system(usage.FALLBACK_LLM)
        return self._local_factory()

    def json_fallback(self, error: Exception) -> LLMProvider | None:
        """The local provider to try after the cloud's answers were not valid JSON twice (None: nothing left to try)."""
        return None if self.fell_back else self._fall_back(error, cool_down=False)

    async def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if self.fell_back or cloud_cooldown.active():
            local = self._local_factory() if self.fell_back else self._fall_back("cloud skipped after a recent failure", cool_down=False)
            return await local.chat(system, user, json_mode=json_mode)
        try:
            return await self.primary.chat(system, user, json_mode=json_mode)
        except LLMError as e:
            local = self._fall_back(e, cool_down=True)
        return await local.chat(system, user, json_mode=json_mode)

    async def stream(self, system: str, user: str, *, json_mode: bool = False) -> AsyncIterator[str]:
        if self.fell_back or cloud_cooldown.active():
            local = self._local_factory() if self.fell_back else self._fall_back("cloud skipped after a recent failure", cool_down=False)
            async for piece in local.stream(system, user, json_mode=json_mode):
                yield piece
            return
        started = False
        try:
            async for piece in self.primary.stream(system, user, json_mode=json_mode):
                started = True
                yield piece
            return
        except LLMError as e:
            if started:
                raise  # the reader already has part of the answer: starting over would repeat it
            local = self._fall_back(e, cool_down=True)
        async for piece in local.stream(system, user, json_mode=json_mode):
            yield piece


def make_provider():
    """The AI service chosen on the settings page (the cloud one falls back to local Ollama unless switched off)."""
    if settings.llm_backend == "cloud":
        cloud = OpenAICompatProvider()
        return FallbackProvider(cloud) if settings.fallback_local else cloud
    return OllamaProvider()


async def chat_json(provider: LLMProvider, system: str, user: str, schema: type[T]) -> T:
    """Ask for JSON, validate against `schema`, retry once on bad output; a cloud provider that still fails
    hands the question to the local model."""
    try:
        return await _ask_json(provider, system, user, schema)
    except LLMError as e:
        fallback = getattr(provider, "json_fallback", None)
        local = fallback(e) if fallback else None
        if local is None:
            raise
        return await _ask_json(local, system, user, schema)


async def _ask_json(provider: LLMProvider, system: str, user: str, schema: type[T]) -> T:
    last_err: Exception | None = None
    for _ in range(2):
        raw = await provider.chat(system, user, json_mode=True)
        try:
            return schema.model_validate(json.loads(_strip_fence(raw)))
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
    raise LLMError(f"模型輸出不是有效的 JSON：{last_err}")


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text.strip()
