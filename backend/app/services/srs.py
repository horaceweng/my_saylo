"""When to show a saved phrase again: a simplified SM-2 (the scheduling behind SuperMemo and Anki).

After each review the learner says how it went. Remembered phrases come back after a longer and longer gap;
forgotten ones start over. `ease` is how fast the gap grows for this phrase (2.5 = it multiplies by 2.5).
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

AGAIN, HARD, GOOD, EASY = 0, 1, 2, 3
MIN_EASE = 1.3
MAX_INTERVAL_DAYS = 365
RETRY_MINUTES = 10  # a forgotten phrase is shown again later in the same sitting


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Card:
    reps: int = 0  # times in a row it was remembered
    interval_days: float = 0.0
    ease: float = 2.5
    lapses: int = 0  # times it was forgotten


def schedule(card: Card, grade: int, now: datetime | None = None) -> tuple[Card, datetime]:
    """The card after a review, and when it is due next."""
    if grade not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError("grade must be 0 (again), 1 (hard), 2 (good) or 3 (easy)")
    now = now or utcnow()
    if grade == AGAIN:
        return (
            replace(card, reps=0, interval_days=0.0, ease=max(MIN_EASE, card.ease - 0.2), lapses=card.lapses + 1),
            now + timedelta(minutes=RETRY_MINUTES),
        )
    reps = card.reps + 1
    previous = card.interval_days
    if grade == HARD:
        interval = 1.0 if reps == 1 else max(previous + 1, previous * 1.2)
        ease = max(MIN_EASE, card.ease - 0.15)
    elif grade == GOOD:
        interval = 1.0 if reps == 1 else 6.0 if reps == 2 else max(previous + 1, previous * card.ease)
        ease = card.ease
    else:
        interval = 4.0 if reps == 1 else max(previous + 2, previous * card.ease * 1.3)
        ease = card.ease + 0.15
    interval = min(MAX_INTERVAL_DAYS, round(interval, 1))
    return replace(card, reps=reps, interval_days=interval, ease=round(ease, 2)), now + timedelta(days=interval)
