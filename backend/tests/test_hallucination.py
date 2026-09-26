from app.services.hallucination import RawSegment, drop_hallucinations, reason_to_drop
from app.services.segmenter import Word
from app.services.transcribe import segments_from_result


def seg(start, end, text, logp=-0.15, nosp=0.0, comp=1.6, prob=0.98):
    words = [Word(w, start, end, prob) for w in text.split()]
    return RawSegment(start, end, text, logp, nosp, comp, words)


SPEECH = [seg(200, 205, "According to some studies, the pain does not get any better."),
          seg(213.1, 218.7, "So torment your heat receptors all you want, but remember, you're going to get burned.")]


def kept_texts(segments):
    return [s.text for s in drop_hallucinations(segments)[0]]


def test_normal_speech_is_untouched():
    kept, dropped = drop_hallucinations(SPEECH)
    assert kept == SPEECH and dropped == []


def test_failed_decode_at_the_end_is_dropped():
    # numbers taken from the real outro of the test video: gibberish decoded with avg_logprob -1.74
    garbage = seg(218.7, 228.1, "In fact, we're going to get intoicode and show it", logp=-1.74, comp=1.92, prob=0.2)
    assert kept_texts(SPEECH + [garbage]) == [s.text for s in SPEECH]
    assert "decoder unsure" in reason_to_drop(garbage, 0)


def test_unlucky_low_confidence_word_inside_good_speech_stays():
    s = seg(110, 117, "A sweet bell pepper gets zero Scoville heat units", prob=0.95)
    s.words[3] = Word("zero", 112, 112.4, 0.16)  # one shaky word among confident ones
    assert kept_texts(SPEECH + [s]) == [x.text for x in SPEECH] + [s.text]


def test_stock_phrase_after_long_silence_is_dropped_but_a_real_thank_you_stays():
    stray = seg(229.9, 231.0, "Thank you.", logp=-0.60)  # 11 s after the last speech, over outro music
    assert kept_texts(SPEECH + [stray]) == [s.text for s in SPEECH]
    genuine = seg(219.3, 220.1, "Thank you.", logp=-0.30)  # right after the closing sentence
    assert kept_texts(SPEECH + [genuine])[-1] == "Thank you."


REAL_GARBAGE = ("Before we read this Then here we'll keep our話 content of candora cal sparkled man...осcmeloogandoora "
                "внимание content of candora gar dot com detailed cmph dot")


def test_the_real_invented_outro_is_dropped_even_when_it_was_decoded_confidently():
    # from the test video; 8.5% of its letters are Cyrillic/CJK
    assert reason_to_drop(seg(222, 231, REAL_GARBAGE), silence_before=1) == "not English text"


def test_non_latin_letters_after_a_long_silence_are_dropped_but_not_in_the_middle_of_speech():
    assert reason_to_drop(seg(230, 233, "Thanks 話 everyone for coming along today"), silence_before=10) == "not English text"
    assert reason_to_drop(seg(30, 33, "Thanks 話 everyone for coming along today"), silence_before=0.4) is None


def test_a_sentence_that_quotes_a_foreign_word_is_kept():
    assert reason_to_drop(seg(1, 3, "We call it 'wasabi', or 山葵 in Chinese, and it is spicy."), 0) is None


def test_subtitle_credits_are_dropped():
    assert reason_to_drop(seg(230, 233, "Subtitles by the Amara.org community"), 5) is not None


def test_repetition_loop_and_silence_and_unrecognised_words():
    assert "repetition" in reason_to_drop(seg(1, 5, "the the the the the the", comp=3.1), 0)
    assert "silence" in reason_to_drop(seg(1, 5, "hmm okay", logp=-0.7, nosp=0.9), 0)
    assert "unrecognised" in reason_to_drop(seg(1, 5, "some words here", prob=0.3), 0)


def test_empty_placeholder_segments_are_ignored():
    assert kept_texts(SPEECH + [seg(228.1, 228.1, "")]) == [s.text for s in SPEECH]


def test_if_everything_looks_doubtful_nothing_is_erased():
    poor = [seg(1, 4, "muffled lecture one", logp=-1.3), seg(4, 8, "muffled lecture two", logp=-1.4)]
    kept, dropped = drop_hallucinations(poor)
    assert kept == poor and dropped == []


def test_gap_is_measured_from_the_last_kept_segment_not_from_dropped_junk():
    junk = seg(219, 228, "gibberish", logp=-2.0)
    stray = seg(228.5, 229.5, "Thank you.", logp=-0.5)  # 9.8 s after the real speech ended at 218.7
    assert kept_texts(SPEECH + [junk, stray]) == [s.text for s in SPEECH]


def test_segments_from_whisper_result_carry_the_confidence_fields():
    result = {"segments": [{"start": 0, "end": 2, "text": " Hi.", "avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.1,
                            "words": [{"word": " Hi.", "start": 0, "end": 1, "probability": 0.9}]}]}
    (s,) = segments_from_result(result)
    assert (s.avg_logprob, s.no_speech_prob, s.compression_ratio) == (-0.2, 0.01, 1.1)
    assert s.words[0].text == " Hi." and s.words[0].prob == 0.9
