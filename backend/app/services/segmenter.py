"""Regroup whisper's word stream into full sentences.

A sentence ends where the text says it does. Only a sentence too long to study as one piece is cut, and then at a
comma or a pause, never at a fixed word count: cutting "…who takes money from the poor to fund | his lavish
lifestyle" in two leaves two halves that make no sense alone (and no sensible translation)."""

import re
from dataclasses import dataclass, field

SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]]*$")  # a full stop, ! or ?, perhaps followed by closing quotes
CLAUSE_END = re.compile(r"[,;:—–][\"'”’)\]]*$")
PAUSE_SECONDS = 0.7  # a pause this long after a comma ends the sentence too
LONG_PAUSE_SECONDS = 1.2  # …and without any punctuation it has to be longer
SOFT_WORDS = 40  # past this many words the sentence is cut at the next comma
HARD_WORDS = 70  # past this many, at the longest pause among the last few words
LOOK_BACK = 15
# "Mr." and friends end in a full stop but not the sentence
ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "jr.", "sr.", "vs.", "mt.", "gen.", "col.", "capt.", "lt.", "sgt."}


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0


@dataclass
class Sentence:
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text.strip() for w in self.words).strip()

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end


def _ends_sentence(text: str, next_text: str | None) -> bool:
    text = text.strip()
    if text.lower() in ABBREVIATIONS or re.fullmatch(r"[A-Z]\.", text):  # "Dr." and the initial in "J. Smith"
        return False
    if SENTENCE_END.search(text) is None:
        return False
    # ...book?" thought Alice: after a closing quote a lower-case word goes on with the same sentence
    closed_quote = re.search(r"[.!?…][\"'”’)\]]+$", text) is not None
    return not (closed_quote and next_text is not None and next_text.strip()[:1].islower())


def split_sentences(words: list[Word]) -> list[Sentence]:
    sentences: list[Sentence] = []
    current: list[Word] = []
    for i, word in enumerate(words):
        current.append(word)
        text = word.text.strip()
        next_word = words[i + 1] if i + 1 < len(words) else None
        gap = next_word.start - word.end if next_word is not None else 0.0
        clause_end = CLAUSE_END.search(text) is not None
        if _ends_sentence(text, next_word.text if next_word is not None else None) or (gap > PAUSE_SECONDS and clause_end) or gap > LONG_PAUSE_SECONDS:
            sentences.append(Sentence(current))
            current = []
        elif len(current) >= SOFT_WORDS and clause_end:
            sentences.append(Sentence(current))
            current = []
        elif len(current) >= HARD_WORDS:
            # no comma anywhere: cut where the speaker paused longest
            first = len(current) - LOOK_BACK
            gaps = [(current[j + 1].start - current[j].end, j) for j in range(first, len(current) - 1)]
            cut = max(gaps)[1] + 1 if gaps else len(current)
            sentences.append(Sentence(current[:cut]))
            current = current[cut:]
    if current:
        sentences.append(Sentence(current))
    return sentences
