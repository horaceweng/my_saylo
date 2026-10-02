import gc
import logging
import sys
import threading

from app.config import settings
from app.services import usage
from app.services.compute import Cooldown, heavy
from app.services.hallucination import RawSegment, drop_hallucinations
from app.services.segmenter import Word

log = logging.getLogger("uvicorn.error")

SAMPLE_RATE = 16000

# After the cloud recogniser failed it is skipped for a minute (each piece would otherwise retry it for ~12 s first).
cloud_cooldown = Cooldown(60.0)


def release_whisper_memory() -> None:
    """Drop the loaded whisper model and give mlx's cached buffers back. Does nothing when mlx was never loaded
    (always the case in tests, which must not pull a model in)."""
    holder = sys.modules.get("mlx_whisper.transcribe")
    if holder is not None and hasattr(holder, "ModelHolder"):
        holder.ModelHolder.model = None
        holder.ModelHolder.model_path = None
    gc.collect()
    clear_mlx_cache()


def clear_mlx_cache() -> None:
    mx = sys.modules.get("mlx.core")
    if mx is None:
        return
    clear = getattr(mx, "clear_cache", None) or getattr(getattr(mx, "metal", None), "clear_cache", None)
    if clear:
        clear()


heavy.register_unloader("whisper", release_whisper_memory)

_idle_timer: threading.Timer | None = None


def _release_when_idle() -> None:
    heavy.run_if_idle("whisper", release_whisper_memory)


def _schedule_idle_release() -> None:
    """The model stays loaded between the pieces of one video, but not for longer than `local_keep_alive_seconds`."""
    global _idle_timer
    if _idle_timer is not None:
        _idle_timer.cancel()
    _idle_timer = threading.Timer(settings.local_keep_alive_seconds, _release_when_idle)
    _idle_timer.daemon = True
    _idle_timer.start()


def run_whisper(audio, *, timeout: float | None = None, **options) -> dict:
    """Recognise speech with the local mlx-whisper model, one at a time (see services/compute.py).
    `audio` is a file path or 16 kHz samples. Raises `compute.Busy` when `timeout` seconds pass without its turn."""
    import mlx_whisper  # heavy import, keep lazy

    with heavy.hold("whisper", timeout):
        try:
            return mlx_whisper.transcribe(audio, path_or_hf_repo=settings.whisper_model, word_timestamps=True, language="en", **options)
        finally:
            clear_mlx_cache()
            _schedule_idle_release()


def segments_from_result(result: dict, offset: float = 0.0) -> list[RawSegment]:
    """`offset` is added to every time, for a result that covers a slice of a longer recording."""
    segments = []
    for seg in result["segments"]:
        words = [Word(w["word"], w["start"] + offset, w["end"] + offset, w.get("probability", 1.0)) for w in seg.get("words", [])]
        segments.append(
            RawSegment(
                start=seg["start"] + offset, end=seg["end"] + offset, text=seg["text"],
                avg_logprob=seg.get("avg_logprob", 0.0), no_speech_prob=seg.get("no_speech_prob", 0.0),
                compression_ratio=seg.get("compression_ratio", 0.0), words=words,
            )
        )
    return segments


def transcribe_words(audio_path: str) -> list[Word]:
    """Run mlx-whisper on `audio_path`, return a flat list of timed words with invented text removed."""
    result = run_whisper(audio_path)
    kept, dropped = drop_hallucinations(segments_from_result(result))
    for d in dropped:
        log.warning("dropped %.1f-%.1fs %r: %s", d.segment.start, d.segment.end, d.segment.text.strip()[:60], d.reason)
    return [w for seg in kept for w in seg.words]


def load_audio(audio_path: str):
    """The whole recording as 16 kHz mono samples; decoded once and sliced for each piece."""
    from mlx_whisper.audio import load_audio as _load

    return _load(audio_path)


def recognise(samples) -> dict:
    """Speech to text for a stretch of audio: the cloud service when chosen (no model runs on this Mac), and when it
    fails the local whisper does the stretch instead (unless switched off). Every fallback is logged and counted."""
    if settings.stt_backend != "cloud":
        return run_whisper(samples)
    from app.services import cloud_stt

    def fall_back(reason: object) -> dict:
        log.warning("cloud speech recognition failed (%s); using local whisper instead", reason)
        usage.record_system(usage.FALLBACK_STT)
        return run_whisper(samples)

    if cloud_cooldown.active():
        return fall_back("cloud skipped after a recent failure") if settings.fallback_local else cloud_stt.transcribe_samples(samples)
    try:
        return cloud_stt.transcribe_samples(samples)
    except cloud_stt.CloudSTTError as e:
        if not settings.fallback_local:
            raise
        cloud_cooldown.start()
        return fall_back(e)


def transcribe_span(audio, t0: float, t1: float) -> tuple[list[Word], list[Word]]:
    """Transcribe seconds t0..t1 of `audio`. Returns (words, doubtful words), both with times in the whole
    recording. Text the hallucination filter sets aside is returned separately rather than thrown away."""
    piece = audio[int(t0 * SAMPLE_RATE) : int(t1 * SAMPLE_RATE)]
    result = recognise(piece)
    kept, dropped = drop_hallucinations(segments_from_result(result, offset=t0), start_at=t0, keep_all_if_doubtful=False)
    for d in dropped:
        log.warning("dropped %.1f-%.1fs %r: %s", d.segment.start, d.segment.end, d.segment.text.strip()[:60], d.reason)
    return [w for seg in kept for w in seg.words], [w for d in dropped for w in d.segment.words]
