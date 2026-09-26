"""Speech recognition by a cloud service with the OpenAI transcription API (Groq, OpenAI …).

Same result as the local Whisper: sentences with the time of every word. A stretch of the recording is sent as a
small mp3; the service answers in `verbose_json` with segments and words."""

import subprocess
import time

import httpx
import numpy as np

from app.config import settings

SAMPLE_RATE = 16000
MAX_TRIES = 4
TIMEOUT = 180


class CloudSTTError(RuntimeError):
    """The cloud recogniser could not be used; the message says why."""


def encode_mp3(samples: np.ndarray) -> bytes:
    """16 kHz mono samples (floats, -1..1) → a small mp3: five minutes are about a megabyte."""
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    run = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-b:a", "32k", "-f", "mp3", "pipe:1"],
        input=pcm, capture_output=True,
    )
    if run.returncode != 0 or not run.stdout:
        raise CloudSTTError("無法把音訊轉成 mp3（ffmpeg 失敗）")
    return run.stdout


def http_message(response: httpx.Response) -> str:
    code = response.status_code
    try:
        detail = response.json()["error"]["message"]
    except Exception:  # noqa: BLE001
        detail = response.text
    detail = str(detail).strip().replace("\n", " ")[:200]
    if code in (401, 403):
        return f"語音辨識服務拒絕了 API 金鑰（HTTP {code}）：請到「設定」檢查金鑰"
    if code == 404:
        return "語音辨識服務找不到這個模型或網址：請到「設定」檢查 Base URL 與模型名稱"
    if code == 413:
        return "音檔太大，超過語音辨識服務的上限"
    if code == 429:
        return "語音辨識服務的速率或額度已達上限，請稍後再試"
    return f"語音辨識服務回報錯誤（HTTP {code}）：{detail}"


def to_whisper_result(data: dict) -> dict:
    """The service's answer in the shape mlx-whisper returns: every segment holds its own words.
    (The API lists the words apart from the segments.)"""
    segments = [dict(s, words=[]) for s in data.get("segments") or []]
    for w in data.get("words") or []:
        start, end = float(w["start"]), float(w["end"])
        mid = (start + end) / 2
        home = next((s for s in segments if s["start"] - 0.05 <= mid <= s["end"] + 0.05), None)
        if home is None and segments:
            home = min(segments, key=lambda s: min(abs(s["start"] - mid), abs(s["end"] - mid)))
        if home is not None:
            home["words"].append({"word": w["word"], "start": start, "end": end})  # no confidence is given
    if not segments and data.get("words"):
        words = [{"word": w["word"], "start": float(w["start"]), "end": float(w["end"])} for w in data["words"]]
        segments = [{"start": words[0]["start"], "end": words[-1]["end"], "text": data.get("text", ""), "words": words}]
    return {"text": data.get("text", ""), "segments": segments}


def transcribe_mp3(audio: bytes, client: httpx.Client | None = None, sleep=time.sleep) -> dict:
    """Send one piece; returns the whisper-shaped result. A busy service (429, 5xx) is asked again after a pause."""
    url = f"{settings.stt_base_url.rstrip('/')}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"} if settings.stt_api_key else {}
    files = {"file": ("piece.mp3", audio, "audio/mpeg")}
    data = {"model": settings.stt_model, "response_format": "verbose_json", "language": "en",
            "timestamp_granularities[]": ["word", "segment"]}
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        for attempt in range(MAX_TRIES):
            try:
                resp = client.post(url, headers=headers, files=files, data=data)
            except httpx.HTTPError as e:
                if attempt == MAX_TRIES - 1:
                    raise CloudSTTError(f"連不上語音辨識服務：{type(e).__name__}") from e
                sleep(2 * (attempt + 1))
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_TRIES - 1:
                try:
                    wait = float(resp.headers.get("retry-after", ""))
                except ValueError:
                    wait = 3.0 * (attempt + 1)
                sleep(min(wait, 60.0))
                continue
            if resp.status_code >= 400:
                raise CloudSTTError(http_message(resp))
            try:
                return to_whisper_result(resp.json())
            except (ValueError, KeyError, TypeError) as e:
                raise CloudSTTError("語音辨識服務的回覆格式不對，請確認 Base URL 是 OpenAI 相容的網址") from e
    finally:
        if own:
            client.close()
    raise CloudSTTError("語音辨識服務沒有回應")  # unreachable: the loop returns or raises


def transcribe_samples(samples: np.ndarray) -> dict:
    return transcribe_mp3(encode_mp3(samples))
