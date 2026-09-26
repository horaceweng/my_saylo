"""Estimate how hard a book is: which share of its words are hard, and how long its sentences are."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from app.services import dictionary
from app.services.books import sentences

_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
HARD_LEVEL = 2  # dictionary levels: 0 basic, 1 CET4, 2 CET6, 3 TOEFL/IELTS, 4 GRE/rare. "Hard" = beyond CET4.


@dataclass
class Metrics:
    words: int  # all word tokens
    known: int  # tokens found in the dictionary (proper nouns and invented words are left out)
    sentences: int
    avg_sentence_words: float
    hard_ratio: float  # share of known tokens beyond CET6 (level >= HARD_LEVEL)
    mid_ratio: float  # share of known tokens at CET6 level or harder


@lru_cache(maxsize=50_000)
def _level(word: str) -> int | None:
    entry = dictionary.lookup(word)
    return None if entry is None else entry.level


def analyze(paragraphs: Iterable[str]) -> Metrics:
    words = known = hard = mid = sentence_count = sentence_words = 0
    for paragraph in paragraphs:
        for sentence in sentences(paragraph):
            tokens = _WORD.findall(sentence)
            if not tokens:
                continue
            sentence_count += 1
            sentence_words += len(tokens)
            words += len(tokens)
            for i, token in enumerate(tokens):
                if i > 0 and token[0].isupper():
                    continue  # a capital in the middle of a sentence: a name, not vocabulary
                level = _level(token.lower().strip("'’-"))
                if level is None:
                    continue
                known += 1
                hard += level >= HARD_LEVEL
                mid += level >= 2
    return Metrics(
        words=words, known=known, sentences=sentence_count,
        avg_sentence_words=sentence_words / sentence_count if sentence_count else 0.0,
        hard_ratio=hard / known if known else 0.0, mid_ratio=mid / known if known else 0.0,
    )


# Calibrated on twelve public-domain books, from The Wonderful Wizard of Oz to Moby-Dick, and on news
# from VOA Learning English, BBC, NPR and the Guardian (see PLAN.md): the share of words beyond CET4
# counts most, sentence length adds to it.
SENTENCE_WEIGHT = 0.5
LEVELS = [("A2", 12.0), ("B1", 15.0), ("B2", 18.5)]  # below the limit → that level; anything above is C1+


def score(metrics: Metrics) -> float:
    return round(100 * metrics.hard_ratio + SENTENCE_WEIGHT * metrics.avg_sentence_words, 2)


def cefr_level(value: float) -> str:
    for name, limit in LEVELS:
        if value < limit:
            return name
    return "C1+"


def grade(paragraphs: Iterable[str]) -> tuple[str, float, Metrics]:
    """(level, score, details). An estimate to sort books by difficulty, not an official CEFR rating."""
    metrics = analyze(paragraphs)
    value = score(metrics)
    return cefr_level(value), value, metrics


# Bump this whenever the formula, the thresholds or the dictionary's difficulty levels change: books and
# articles saved earlier are then graded again the next time the server starts (see regrade_all).
GRADING_VERSION = "3"
