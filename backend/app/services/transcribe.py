import logging
import threading

from app.config import settings
from app.services.hallucination import RawSegment, drop_hallucinations
from app.services.segmenter import Word

log = logging.getLogger(__name__)

# mlx-whisper must not run in two threads at once (a video job and a shadowing comparison could overlap).
whisper_lock = threading.Lock()


SAMPLE_RATE = 16000


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
    import mlx_whisper  # heavy import, keep lazy

    with whisper_lock:
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=settings.whisper_model,
            word_timestamps=True,
            language="en",
        )
    kept, dropped = drop_hallucinations(segments_from_result(result))
    for d in dropped:
        log.warning("dropped %.1f-%.1fs %r: %s", d.segment.start, d.segment.end, d.segment.text.strip()[:60], d.reason)
    return [w for seg in kept for w in seg.words]


def load_audio(audio_path: str):
    """The whole recording as 16 kHz mono samples; decoded once and sliced for each piece."""
    from mlx_whisper.audio import load_audio as _load

    return _load(audio_path)


def transcribe_span(audio, t0: float, t1: float) -> tuple[list[Word], list[Word]]:
    """Transcribe seconds t0..t1 of `audio`. Returns (words, doubtful words), both with times in the whole
    recording. Text the hallucination filter sets aside is returned separately rather than thrown away."""
    piece = audio[int(t0 * SAMPLE_RATE) : int(t1 * SAMPLE_RATE)]
    if settings.stt_backend == "cloud":
        from app.services import cloud_stt

        result = cloud_stt.transcribe_samples(piece)  # no model runs on this Mac
    else:
        import mlx_whisper  # heavy import, keep lazy

        with whisper_lock:
            result = mlx_whisper.transcribe(piece, path_or_hf_repo=settings.whisper_model, word_timestamps=True, language="en")
    kept, dropped = drop_hallucinations(segments_from_result(result, offset=t0), start_at=t0, keep_all_if_doubtful=False)
    for d in dropped:
        log.warning("dropped %.1f-%.1fs %r: %s", d.segment.start, d.segment.end, d.segment.text.strip()[:60], d.reason)
    return [w for seg in kept for w in seg.words], [w for d in dropped for w in d.segment.words]
