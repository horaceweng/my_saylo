"""Transcribe a long recording in pieces so the first sentences are available after seconds, not minutes.

A piece is cut at an arbitrary time, so the sentence at its end is usually unfinished. Each piece is
transcribed a little past its end, its last sentence is set aside, and the next piece starts where
that sentence began. No sentence is cut in half, lost or repeated.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app.services.segmenter import Sentence, Word, split_sentences

CHUNK_SECONDS = 300
OVERLAP_SECONDS = 20  # transcribed beyond the piece so the sentence crossing its end can be completed
MIN_ADVANCE = 1.0  # a piece always moves the start forward at least this much, so the loop cannot stall


@dataclass
class Piece:
    sentences: list[Sentence]
    frontier: float  # everything before this time has been turned into sentences
    doubtful: list[Word]  # words the hallucination filter set aside (kept in case the whole file is doubtful)


def transcribe_in_pieces(
    transcribe_span: Callable[[float, float], tuple[list[Word], list[Word]]],
    duration: float,
    start: float = 0.0,
    chunk: float = CHUNK_SECONDS,
    overlap: float = OVERLAP_SECONDS,
) -> Iterator[Piece]:
    """`transcribe_span(t0, t1)` returns (words, doubtful words) with absolute times for that stretch."""
    t0 = start
    while t0 < duration:
        t1 = min(t0 + chunk + overlap, duration)
        final = t1 >= duration
        words, doubtful = transcribe_span(t0, t1)
        sentences = split_sentences(words)
        if final:
            emitted, frontier = sentences, duration
        elif len(sentences) >= 2:
            emitted = sentences[:-1]
            frontier = max(sentences[-1].start, t0 + MIN_ADVANCE)  # the last sentence is re-done by the next piece
        else:
            emitted, frontier = sentences, t1  # a quiet stretch or one very long sentence: move past it
        yield Piece(emitted, frontier, doubtful)
        t0 = frontier
