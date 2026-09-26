"""Compare what a learner said with the sentence they were shadowing.

Speech recognition turns the recording into words; those words are aligned with the sentence and each
sentence word is marked ok / unclear / wrong / missing, with extra spoken words marked too.
Limits worth knowing: recognition tends to "fix" accents, so this is lenient, and a low recognition
confidence only says the word was hard to make out, not what exactly was off. It is not phoneme scoring.
"""

import difflib
import re
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from app.config import settings
from app.services.segmenter import Word
from app.services.transcribe import whisper_lock

UNCLEAR_BELOW = 0.5  # recognition confidence under which a matched word counts as unclear


@dataclass
class Token:
    text: str
    status: str  # ok | unclear | wrong | missing | extra
    heard: str | None = None  # for "wrong": what was recognised instead


@dataclass
class Comparison:
    tokens: list[Token]
    score: int  # % of the sentence's words that were spoken (ok + unclear)
    counts: dict[str, int]

    def to_json_list(self) -> list[dict]:
        return [asdict(t) for t in self.tokens]

    def facts(self) -> dict[str, list]:
        """The differences in a compact form for the AI feedback prompt."""
        return {
            "missing": [t.text for t in self.tokens if t.status == "missing"],
            "wrong": [{"expected": t.text, "heard": t.heard} for t in self.tokens if t.status == "wrong"],
            "unclear": [t.text for t in self.tokens if t.status == "unclear"],
            "extra": [t.text for t in self.tokens if t.status == "extra"],
        }


def normalise(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def compare(reference: str, spoken: list[Word]) -> Comparison:
    ref = [w for w in reference.split() if normalise(w)]
    heard = [w for w in spoken if normalise(w.text)]
    ref_keys = [normalise(w) for w in ref]
    heard_keys = [normalise(w.text) for w in heard]

    tokens: list[Token] = []
    matcher = difflib.SequenceMatcher(None, ref_keys, heard_keys, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for r, h in zip(ref[i1:i2], heard[j1:j2]):
                tokens.append(Token(r, "unclear" if h.prob < UNCLEAR_BELOW else "ok"))
        elif op == "delete":
            tokens += [Token(r, "missing") for r in ref[i1:i2]]
        elif op == "insert":
            tokens += [Token(h.text.strip(), "extra") for h in heard[j1:j2]]
        else:  # replace: pair up words in order, whatever is left over is missing or extra
            pairs = min(i2 - i1, j2 - j1)
            tokens += [Token(ref[i1 + k], "wrong", heard[j1 + k].text.strip()) for k in range(pairs)]
            tokens += [Token(r, "missing") for r in ref[i1 + pairs : i2]]
            tokens += [Token(h.text.strip(), "extra") for h in heard[j1 + pairs : j2]]

    counts = {s: sum(1 for t in tokens if t.status == s) for s in ("ok", "unclear", "wrong", "missing", "extra")}
    spoken_count = counts["ok"] + counts["unclear"]
    score = round(100 * spoken_count / len(ref)) if ref else 0
    return Comparison(tokens, score, counts)


# ---- audio helpers ----------------------------------------------------------------------

SILENT_RMS = 0.003  # about -50 dBFS: nothing was picked up by the microphone
LOCK_WAIT_SECONDS = 90


class AudioError(ValueError):
    pass


class TranscriberBusy(RuntimeError):
    pass


def _ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(proc.stderr.strip()[-300:] or "ffmpeg failed")


def to_wav16k(src: Path, dst: Path) -> None:
    """Whatever the browser recorded (webm/opus, mp4) → 16 kHz mono wav, which speech recognition expects."""
    _ffmpeg(["-i", str(src), "-ac", "1", "-ar", "16000", str(dst)])


def extract_clip(audio: Path, start: float, end: float, dst: Path) -> None:
    """The part of a video's audio that holds one sentence, with a little room on both sides."""
    _ffmpeg(["-ss", f"{max(0.0, start - 0.15):.3f}", "-to", f"{end + 0.15:.3f}", "-i", str(audio), "-ac", "1", "-ar", "22050", str(dst)])


def wav_stats(path: Path) -> tuple[float, float]:
    """(duration in seconds, rms loudness 0..1) of a 16-bit wav file."""
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        duration = w.getnframes() / w.getframerate()
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64) / 32768
    return duration, float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0


def transcribe_recording(wav: Path) -> list[Word]:
    """Recognise a short recording. Doubtful words are kept (that is the signal we want); only text
    the recogniser itself flags as 'no speech here' is dropped."""
    import mlx_whisper  # heavy import, keep lazy

    if not whisper_lock.acquire(timeout=LOCK_WAIT_SECONDS):
        raise TranscriberBusy("語音辨識正在處理影片，請稍後再試")
    try:
        result = mlx_whisper.transcribe(
            str(wav), path_or_hf_repo=settings.whisper_model, word_timestamps=True, language="en",
            condition_on_previous_text=False,
        )
    finally:
        whisper_lock.release()
    words: list[Word] = []
    for seg in result["segments"]:
        if seg.get("no_speech_prob", 0) > 0.6 and seg.get("avg_logprob", 0) < -0.5:
            continue
        words += [Word(w["word"], w["start"], w["end"], w.get("probability", 1.0)) for w in seg.get("words", [])]
    return words


# ---- keeping the AI feedback honest -----------------------------------------------------

# The model only sees a text comparison, yet a small model still likes to write phonetic symbols and
# describe tongue or lip positions, and gets them wrong. Anything like that is removed after the fact.
_IPA = re.compile(r"[ɪəɜɔʊʌæɑθðʃʒŋɡɒɛɹɾˈˌ]|[a-zA-Z]ː")
_ARTICULATION = ("舌", "唇", "口型", "嘴型", "喉嚨", "喉音", "氣流", "鼻腔", "顎")
FALLBACK_TIP = "重聽一次原音，放慢速度再跟著念一次。"


def _made_up_detail(text: str) -> bool:
    return bool(_IPA.search(text)) or any(word in text for word in _ARTICULATION)


def sanitize_feedback(data: dict) -> dict:
    """Drop advice and sentences that claim phonetic detail; works on partial or finished feedback."""
    out = dict(data)
    if isinstance(out.get("summary"), str):
        sentences = re.findall(r"[^。！？!?]*[。！？!?]?", out["summary"])
        out["summary"] = "".join(x for x in sentences if x and not _made_up_detail(x))
    if isinstance(out.get("tips"), list):
        out["tips"] = [t for t in out["tips"] if isinstance(t, str) and not _made_up_detail(t)]
    return out


def finish_feedback(data: dict) -> dict:
    """Final version: sanitised, and never left without a practical suggestion."""
    out = sanitize_feedback(data)
    if not out.get("tips"):
        out["tips"] = [FALLBACK_TIP]
    return out
