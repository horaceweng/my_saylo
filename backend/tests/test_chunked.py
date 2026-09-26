from app.services.chunked import transcribe_in_pieces
from app.services.segmenter import Word


def speech(n_sentences, sentence_seconds=4.0, gap=0.5, words_per_sentence=4):
    """A fake recording: sentence i covers [i*(s+gap), i*(s+gap)+s]; its words are evenly spread."""
    words, t = [], 0.0
    for i in range(n_sentences):
        step = sentence_seconds / words_per_sentence
        for j in range(words_per_sentence):
            text = f"s{i}w{j}" + ("." if j == words_per_sentence - 1 else "")
            words.append(Word(text, t + j * step, t + (j + 1) * step - 0.05))
        t += sentence_seconds + gap
    return words


def fake_transcriber(all_words, calls):
    """Returns the words of the recording that fall inside the requested stretch, like whisper would."""
    def run(t0, t1):
        calls.append((round(t0, 1), round(t1, 1)))
        return [w for w in all_words if w.start >= t0 - 1e-9 and w.end <= t1 + 1e-9], []
    return run


def collect(all_words, duration, **kw):
    calls = []
    pieces = list(transcribe_in_pieces(fake_transcriber(all_words, calls), duration, **kw))
    return pieces, calls


def texts(pieces):
    return [s.text for p in pieces for s in p.sentences]


def test_every_sentence_comes_out_exactly_once_and_in_order():
    words = speech(100)  # 450 s of speech
    pieces, calls = collect(words, duration=450, chunk=100, overlap=15)
    got = texts(pieces)
    assert got == [f"s{i}w0 s{i}w1 s{i}w2 s{i}w3." for i in range(100)]
    assert len(calls) > 3  # it really was done in several pieces


def test_a_sentence_crossing_the_end_of_a_piece_is_finished_in_the_next_one_not_cut():
    words = speech(30)
    pieces, calls = collect(words, duration=140, chunk=50, overlap=15)
    for s in (s for p in pieces for s in p.sentences):
        assert s.text.endswith(".") and len(s.words) == 4  # never half a sentence
    # the second piece starts where a sentence starts, not at the round number 50
    assert calls[1][0] != 50 and calls[1][0] > 0


def test_frontier_grows_and_the_last_piece_reaches_the_end():
    pieces, _ = collect(speech(60), duration=270, chunk=60, overlap=15)
    frontiers = [p.frontier for p in pieces]
    assert frontiers == sorted(frontiers) and len(set(frontiers)) == len(frontiers)
    assert frontiers[-1] == 270


def test_a_quiet_stretch_is_skipped_and_the_loop_still_ends():
    words = speech(3) + [Word(w.text, w.start + 500, w.end + 500) for w in speech(3)]  # silence in between
    pieces, _ = collect(words, duration=520, chunk=100, overlap=15)
    assert len(texts(pieces)) == 6


def test_one_endless_sentence_does_not_stall():
    words = [Word("word", i * 0.3, i * 0.3 + 0.25) for i in range(400)]  # no punctuation; split into 25-word sentences
    pieces, _ = collect(words, duration=120, chunk=40, overlap=10)
    assert sum(len(s.words) for p in pieces for s in p.sentences) == 400


def test_resuming_from_a_time_only_covers_the_rest():
    words = speech(40)
    full, _ = collect(words, duration=180, chunk=60, overlap=15)
    resume_at = full[0].frontier
    rest, calls = collect(words, duration=180, start=resume_at, chunk=60, overlap=15)
    assert texts(full[:1]) + texts(rest) == texts(full)
    assert calls[0][0] == round(resume_at, 1)


def test_doubtful_words_are_passed_along():
    def run(t0, t1):
        return [], [Word("maybe", t0, t0 + 1)]
    pieces = list(transcribe_in_pieces(run, 30, chunk=100, overlap=10))
    assert pieces[0].sentences == [] and [w.text for w in pieces[0].doubtful] == ["maybe"]


def test_empty_recording_gives_nothing():
    assert list(transcribe_in_pieces(lambda a, b: ([], []), 0)) == []
