"""Offline dictionary lookups backed by ECDICT (data/dict.sqlite)."""

import sqlite3
from dataclasses import dataclass
from functools import lru_cache

from app.config import settings

# Difficulty levels used for underline colours: 0 = basic (no underline) … 4 = advanced/rare.
LEVEL_LABELS = ["基礎", "CET4", "CET6", "TOEFL/IELTS", "GRE/罕用"]

# ECDICT `exchange` field prefixes: p=past, d=past participle, i=-ing, 3=3rd person,
# r=comparative, t=superlative, s=plural, 0=lemma, 1=lemma's variant type.


@dataclass
class Entry:
    word: str
    phonetic: str
    definition: str
    translation: str
    pos: str
    tags: list[str]
    bnc: int
    frq: int
    exchange: dict[str, str]
    level: int


# ECDICT lists "they" as the plural of "it" and "some" as the plural of "a": pronouns and articles are
# never the base form of another word for a learner.
_NEVER_A_BASE = {"a", "an", "the", "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his", "she", "her", "it", "its", "this", "that"}


@lru_cache(maxsize=1)
def _conn() -> sqlite3.Connection:
    path = settings.dict_db_path
    if not path.exists():
        raise FileNotFoundError(f"找不到字典 {path}，請先執行 scripts/import_ecdict.py")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def parse_exchange(raw: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in (raw or "").split("/"):
        if ":" in part:
            key, value = part.split(":", 1)
            result[key] = value
    return result


def difficulty_level(tags: list[str], frq: int, bnc: int = 0) -> int:
    """Map ECDICT tags / corpus frequency onto the 5 difficulty levels.

    A word is as hard as the *easiest* exam list it is on: "strict" is on the CET4 and the TOEFL list, and a
    learner who knows CET4 words knows it. Very common words come first, since exam tags such as zk/gk also
    cover basics like "the". Words on no list are placed by how rare they are."""
    frq = frq or bnc  # some entries have only the other corpus's rank ("an", "BBC")
    if frq and frq <= 3000:
        return 0
    have = set(tags)
    if have & {"zk", "gk", "cet4"}:
        return 1
    if have & {"cet6", "ky"}:
        return 2
    if have & {"toefl", "ielts"}:
        return 3
    if "gre" in have:
        return 4
    if frq and frq <= 8000:
        return 1
    if frq and frq <= 20000:
        return 2
    return 3 if frq else 4


def _row_to_entry(row: sqlite3.Row) -> Entry:
    tags = (row["tag"] or "").split()
    frq = row["frq"] or 0
    return Entry(
        word=row["word"],
        phonetic=row["phonetic"] or "",
        definition=row["definition"] or "",
        translation=row["translation"] or "",
        pos=row["pos"] or "",
        tags=tags,
        bnc=row["bnc"] or 0,
        frq=frq,
        exchange=parse_exchange(row["exchange"]),
        level=difficulty_level(tags, frq, row["bnc"] or 0),
    )


def lookup(word: str) -> Entry | None:
    """Exact lookup, following the lemma link for inflected forms (went → go)."""
    word = word.strip().lower()
    row = _conn().execute("SELECT * FROM dict WHERE word = ?", (word,)).fetchone()
    if row is None:
        return None
    entry = _row_to_entry(row)
    lemma = entry.exchange.get("0")
    if lemma and lemma != word:
        lemma_row = _conn().execute("SELECT * FROM dict WHERE word = ?", (lemma,)).fetchone()
        if lemma_row is not None:
            lemma_entry = _row_to_entry(lemma_row)
            # ECDICT's lemma links contain mistakes ("also" → "conjurer", "of" → "have"). Only trust a link
            # when the base word itself lists this word as one of its forms ("go" lists "went").
            listed = word in lemma_entry.exchange.values()
            # "were" is not listed under "be" but says itself that it is a verb form ("1:p" = past tense)
            declared = bool(entry.exchange.get("1")) and set(entry.exchange["1"]) <= set("pdi3rt")
            if lemma_entry.word.lower() not in _NEVER_A_BASE and (listed or declared):
                return lemma_entry
    return entry


def exists(word: str) -> bool:
    return _conn().execute("SELECT 1 FROM dict WHERE word = ?", (word.strip().lower(),)).fetchone() is not None


def frequency_rank(word: str) -> int:
    """Corpus frequency rank (1 = most common); unknown or unranked words sort last."""
    entry = lookup(word)
    return entry.frq if entry and entry.frq else 10**9
