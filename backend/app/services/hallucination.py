"""Drop the text whisper invents when there is no speech (outro music, silence, noise).

Whisper always tries to write *something*, so trailing music turns into gibberish or a stock phrase
("Thank you.", "Subtitles by ..."). Whisper's own `hallucination_silence_threshold` is not used because
on real speech it also deleted and rewrote genuine words. These checks only look at how confident the
decoder was and at what was written, so speech that was transcribed properly is never touched.
"""

import unicodedata
from dataclasses import dataclass, field

from app.services.segmenter import Word

# Whisper itself treats a window below this average log-probability as a failed decode.
FAILED_LOGPROB = -1.0
REPEAT_LOOP_COMPRESSION = 2.4
SILENT_NO_SPEECH = 0.6
SILENT_LOGPROB = -0.5
LOW_WORD_CONFIDENCE = 0.5
# Measured on real text: the invented outro was 8.5% non-Latin letters, an honest sentence quoting a
# Chinese word was 5%. After a long silence any non-Latin letter at all is suspicious.
FOREIGN_SCRIPT_SHARE = 0.07
# A stock phrase counts as invented when it comes after at least this much silence.
STRAY_PHRASE_GAP = 4.0

STOCK_PHRASES = {
    "thank you", "thank you.", "thanks", "thanks for watching", "thank you for watching", "you", "bye", "bye bye",
    "see you next time", "please subscribe", "like and subscribe",
}
CREDIT_MARKERS = ("amara.org", "subtitles by", "subtitled by", "captions by", "captioned by", "transcribed by")


@dataclass
class RawSegment:
    start: float
    end: float
    text: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    compression_ratio: float = 0.0
    words: list[Word] = field(default_factory=list)


@dataclass
class Dropped:
    segment: RawSegment
    reason: str


def _normalise(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum() or c.isspace()).strip()


def _foreign_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    foreign = sum(1 for c in letters if not unicodedata.name(c, "").startswith("LATIN"))
    return foreign / len(letters)


def reason_to_drop(seg: RawSegment, silence_before: float) -> str | None:
    """Why `seg` looks invented, or None to keep it. `silence_before` is the gap since the last kept speech."""
    text = seg.text.strip()
    if seg.avg_logprob < FAILED_LOGPROB:
        return f"decoder unsure (avg_logprob {seg.avg_logprob:.2f})"
    if seg.compression_ratio > REPEAT_LOOP_COMPRESSION:
        return f"repetition loop (compression {seg.compression_ratio:.2f})"
    if seg.no_speech_prob > SILENT_NO_SPEECH and seg.avg_logprob < SILENT_LOGPROB:
        return f"probably silence (no_speech {seg.no_speech_prob:.2f})"
    if seg.words and sum(w.prob for w in seg.words) / len(seg.words) < LOW_WORD_CONFIDENCE:
        return "words mostly unrecognised"
    foreign = _foreign_share(text)
    if foreign > FOREIGN_SCRIPT_SHARE or (foreign > 0 and silence_before >= STRAY_PHRASE_GAP):
        return "not English text"
    if any(marker in text.lower() for marker in CREDIT_MARKERS):
        return "subtitle credit"
    if _normalise(text) in STOCK_PHRASES and silence_before >= STRAY_PHRASE_GAP:
        return f"stock phrase after {silence_before:.0f}s of silence"
    return None


def drop_hallucinations(
    segments: list[RawSegment], start_at: float = 0.0, keep_all_if_doubtful: bool = True
) -> tuple[list[RawSegment], list[Dropped]]:
    """`start_at`: where in the audio these segments begin (the silence-gap rules measure from there).
    `keep_all_if_doubtful`: when everything looks doubtful, keep it rather than erase it all; callers that
    look at one part of a longer file turn this off and decide for the whole file themselves."""
    kept: list[RawSegment] = []
    dropped: list[Dropped] = []
    last_end = start_at
    for seg in segments:
        if not seg.text.strip():
            continue  # empty placeholder segments carry no speech
        reason = reason_to_drop(seg, seg.start - last_end)
        if reason:
            dropped.append(Dropped(seg, reason))
        else:
            kept.append(seg)
            last_end = seg.end
    if keep_all_if_doubtful and not kept and dropped:
        # Everything looks doubtful (very poor audio, heavy accent): better to show it than to erase it all.
        return [d.segment for d in dropped], []
    return kept, dropped
