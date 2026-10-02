"""Natural-sounding read-aloud: the Kokoro neural voice, run on the Mac itself (mlx-audio).

Text comes in as short pieces (a sentence or two), audio goes out as mp3. Every piece is kept on disk, so
reading the same text again costs nothing."""

import hashlib
import importlib.util
import logging
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.services.compute import heavy

log = logging.getLogger("uvicorn.error")

MODEL_REPO = "mlx-community/Kokoro-82M-bf16"
SAMPLE_RATE = 24000
MAX_CHARS = 600
CACHE_DAYS = 30
DEFAULT_VOICE = "af_heart"


@dataclass(frozen=True)
class Voice:
    id: str
    label: str

    @property
    def lang_code(self) -> str:
        return "b" if self.id.startswith("b") else "a"  # british or american English


VOICES = [
    Voice("af_heart", "Heart · 美式女聲（推薦）"),
    Voice("af_bella", "Bella · 美式女聲"),
    Voice("af_nicole", "Nicole · 美式女聲（輕柔）"),
    Voice("af_sarah", "Sarah · 美式女聲"),
    Voice("am_michael", "Michael · 美式男聲"),
    Voice("am_adam", "Adam · 美式男聲（低沉）"),
    Voice("am_puck", "Puck · 美式男聲"),
    Voice("bf_emma", "Emma · 英式女聲"),
    Voice("bf_isabella", "Isabella · 英式女聲"),
    Voice("bm_george", "George · 英式男聲"),
    Voice("bm_daniel", "Daniel · 英式男聲"),
]


class TTSError(RuntimeError):
    """Reading aloud is not possible right now; the message says why and what to do."""


def voice_ids() -> list[str]:
    return [v.id for v in VOICES]


# -- what this computer has -----------------------------------------------------------------------

_ESPEAK_LIBS = ("/opt/homebrew/lib/libespeak-ng.dylib", "/usr/local/lib/libespeak-ng.dylib")


def espeak_paths() -> tuple[str, str] | None:
    """(library, data folder) of espeak-ng, which turns unusual words into sounds. The copy bundled with the
    Python packages cannot find its own data on this setup, so the Homebrew one is used."""
    lib, data = os.environ.get("ESPEAK_LIBRARY"), os.environ.get("ESPEAK_DATA_PATH")
    if lib and data and Path(lib).exists() and Path(data).exists():
        return lib, data
    for candidate in _ESPEAK_LIBS:
        found = Path(candidate)
        folder = found.parent.parent / "share" / "espeak-ng-data"
        if found.exists() and folder.exists():
            return str(found), str(folder)
    return None


def problems() -> list[str]:
    """Why natural reading cannot work here (empty when it can)."""
    out = []
    for module in ("mlx_audio", "misaki", "en_core_web_sm"):
        if importlib.util.find_spec(module) is None:
            out.append(f"缺少 Python 套件 {module}：請在 backend 資料夾執行 uv sync")
    if espeak_paths() is None:
        out.append("找不到 espeak-ng：請執行 brew install espeak-ng")
    return out


def model_downloaded() -> bool:
    """Is the voice model in the local cache (otherwise the first reading downloads about 330 MB)?"""
    from huggingface_hub.constants import HF_HUB_CACHE

    folder = Path(HF_HUB_CACHE) / f"models--{MODEL_REPO.replace('/', '--')}" / "snapshots"
    return any(folder.glob("*/kokoro-v1_0.safetensors"))


# -- making the audio -----------------------------------------------------------------------------

# MLX must be used from the thread that loaded the model, so all synthesis runs on this one thread.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
_model = None
_pruned = False


def _load_model():
    global _model
    if _model is None:
        paths = espeak_paths()
        if paths is None:
            raise TTSError("找不到 espeak-ng：請執行 brew install espeak-ng")
        from phonemizer.backend.espeak.wrapper import EspeakWrapper

        import misaki.espeak  # noqa: F401 - sets its own paths when first imported, so ours go on top

        EspeakWrapper.set_library(paths[0])
        EspeakWrapper.set_data_path(paths[1])
        from mlx_audio.tts.utils import load_model

        t = time.monotonic()
        _model = load_model(MODEL_REPO)
        log.info("Kokoro voice model ready in %.1fs", time.monotonic() - t)
    return _model


def synthesize(text: str, voice: Voice):
    """The spoken text as float samples (24 kHz, mono)."""
    import numpy as np

    with heavy.hold("tts"):  # takes its turn with whisper and Ollama; they are unloaded first (see services/compute.py)
        model = _load_model()
        parts = [np.array(r.audio) for r in model.generate(text=text, voice=voice.id, speed=1.0, lang_code=voice.lang_code)]
    if not parts:
        raise TTSError("這段文字念不出來")
    return np.concatenate(parts)


def to_mp3(samples) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    run = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", "pipe:1"],
        input=pcm, capture_output=True,
    )
    if run.returncode != 0 or not run.stdout:
        raise TTSError("無法轉成 mp3（ffmpeg 失敗）")
    return run.stdout


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def speakable(text: str) -> bool:
    return re.search(r"[A-Za-z0-9]", text) is not None


def cache_dir() -> Path:
    return settings.data_dir / "tts"


def cache_path(text: str, voice_id: str) -> Path:
    key = hashlib.sha1(f"{MODEL_REPO}|{voice_id}|{text}".encode()).hexdigest()
    return cache_dir() / f"{key}.mp3"


def prune_cache(max_age_days: int = CACHE_DAYS, now: float | None = None) -> int:
    """Delete audio that has not been played for a month. Returns how many files went."""
    folder = cache_dir()
    if not folder.exists():
        return 0
    limit = (now if now is not None else time.time()) - max_age_days * 86400
    gone = 0
    for f in folder.glob("*.mp3"):
        if f.stat().st_mtime < limit:
            f.unlink(missing_ok=True)
            gone += 1
    return gone


_write_lock = threading.Lock()


def _make(text: str, voice: Voice, target: Path) -> Path:
    global _pruned
    if target.exists():
        target.touch()  # played again: keep it
        return target
    if not _pruned:
        _pruned = True
        prune_cache()
    t = time.monotonic()
    audio = to_mp3(synthesize(text, voice))
    with _write_lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        tmp.write_bytes(audio)
        tmp.replace(target)
    log.info("spoke %d characters in %.1fs", len(text), time.monotonic() - t)
    return target


def speak_file(text: str, voice_id: str) -> Path:
    """The mp3 of `text` in this voice (made now unless it is already on disk). Blocking: call from a thread."""
    text = normalize(text)
    if not text or not speakable(text):
        raise TTSError("沒有可以朗讀的文字")
    if len(text) > MAX_CHARS:
        raise TTSError(f"一次最多朗讀 {MAX_CHARS} 個字")
    voice = next((v for v in VOICES if v.id == voice_id), None)
    if voice is None:
        raise TTSError("不支援這個聲音")
    target = cache_path(text, voice.id)
    if target.exists():
        return _make(text, voice, target)
    issues = problems()
    if issues:
        raise TTSError("；".join(issues))
    return _executor.submit(_make, text, voice, target).result()
