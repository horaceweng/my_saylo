from app.services.segmenter import Word, split_sentences


def w(text, start, end):
    return Word(text, start, end)


def test_splits_on_sentence_punctuation():
    words = [w("Hello", 0, 0.4), w("world.", 0.4, 0.9), w("How", 1.0, 1.2), w("are", 1.2, 1.4), w("you?", 1.4, 1.8)]
    sentences = split_sentences(words)
    assert [s.text for s in sentences] == ["Hello world.", "How are you?"]
    assert sentences[1].start == 1.0 and sentences[1].end == 1.8


def test_splits_on_long_pause():
    words = [w("one", 0, 0.3), w("two", 0.3, 0.6), w("three", 2.0, 2.3)]
    assert [s.text for s in split_sentences(words)] == ["one two", "three"]


def speak(text, pace=0.3):
    """Words of `text` said one after another without pauses."""
    return [w(token, i * pace, i * pace + pace * 0.8) for i, token in enumerate(text.split())]


def test_a_sentence_of_thirty_one_words_is_not_cut():
    # "Robin has a habit of stealing from the rich … to fund his lavish lifestyle, can't stand him." used to be cut after 25 words
    text = ("Robin has a habit of stealing from the rich to give to the poor, but the sheriff, who takes money from the poor to fund "
            "his lavish lifestyle, can't stand him.")
    assert len(text.split()) == 31
    assert [s.text for s in split_sentences(speak(text))] == [text]


def test_another_sentence_that_was_cut_at_twenty_five_words():
    text = "He thinks of him as a robber and wants to have him arrested on his wedding day of all days, just as he is about to marry the beautiful Maid Marian."
    assert [s.text for s in split_sentences(speak(text))] == [text]


def test_a_very_long_sentence_is_cut_at_a_comma_not_in_the_middle_of_a_phrase():
    clause = "and then the tired old man walked slowly along the winding river road"  # 13 words
    text = ", ".join([clause] * 5) + " until night."  # 67 words
    sentences = split_sentences(speak(text))
    assert len(sentences) == 2 and sentences[0].text.endswith(",") and len(sentences[0].words) == 52
    assert " ".join(s.text for s in sentences) == text


def test_only_a_sentence_of_seventy_words_or_more_without_any_comma_is_cut_at_the_longest_pause():
    words = speak(" ".join(f"w{i}" for i in range(100)))
    words[60 + 1] = w("w61", words[61].start + 0.5, words[61].end + 0.5)  # a small pause among the last words before the limit
    for i in range(62, 100):
        words[i] = w(words[i].text, words[i].start + 0.5, words[i].end + 0.5)
    sentences = split_sentences(words)
    assert all(len(s.words) <= 70 for s in sentences) and sum(len(s.words) for s in sentences) == 100
    assert len(sentences[0].words) == 61  # cut at the pause


def test_closing_quotes_after_the_full_stop_still_end_the_sentence():
    quoted = split_sentences(speak('She said "it is over." Then she left.'))
    assert [s.text for s in quoted] == ['She said "it is over."', "Then she left."]


def test_a_dialogue_tag_after_a_closing_quote_stays_with_the_quote():
    text = '"and what is the use of a book?" thought Alice. Then she left.'
    assert [s.text for s in split_sentences(speak(text))] == ['"and what is the use of a book?" thought Alice.', "Then she left."]


def test_titles_and_initials_do_not_end_a_sentence():
    assert [s.text for s in split_sentences(speak("Dr. Smith met Mr. J. Brown today."))] == ["Dr. Smith met Mr. J. Brown today."]
    assert [s.text for s in split_sentences(speak("It was over. Then we left."))] == ["It was over.", "Then we left."]


def test_a_pause_ends_the_sentence_only_when_it_is_long_enough_for_what_came_before():
    after_comma = [w("Well,", 0, 0.3), w("then", 1.2, 1.5)]  # 0.9 s after a comma
    assert [s.text for s in split_sentences(after_comma)] == ["Well,", "then"]
    no_punctuation = [w("one", 0, 0.3), w("two", 1.2, 1.5)]  # 0.9 s in the middle of a phrase
    assert [s.text for s in split_sentences(no_punctuation)] == ["one two"]


def test_empty_input():
    assert split_sentences([]) == []
