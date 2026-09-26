"""Smoke test: transcribe an audio file and print sentences with word timings."""
import sys

from app.services.segmenter import split_sentences
from app.services.transcribe import transcribe_words

words = transcribe_words(sys.argv[1])
for s in split_sentences(words):
    print(f"[{s.start:6.2f}-{s.end:6.2f}] {s.text}")
print(f"\n{len(words)} words, first 3: {[(w.text, round(w.start, 2), round(w.end, 2)) for w in words[:3]]}")
