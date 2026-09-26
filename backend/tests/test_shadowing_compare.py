from app.services.segmenter import Word
from app.services.shadowing import FALLBACK_TIP, compare, finish_feedback, sanitize_feedback


def said(text, prob=0.98):
    return [Word(w, i * 0.4, i * 0.4 + 0.3, prob) for i, w in enumerate(text.split())]


def statuses(result):
    return [(t.text, t.status, t.heard) for t in result.tokens]


REF = "Why does wasabi make your eyes water?"


def test_perfect_repetition_scores_100_and_ignores_case_and_punctuation():
    r = compare(REF, said("why does wasabi make your eyes water"))
    assert r.score == 100 and all(t.status == "ok" for t in r.tokens)
    assert r.counts == {"ok": 7, "unclear": 0, "wrong": 0, "missing": 0, "extra": 0}


def test_a_skipped_word_is_marked_missing():
    r = compare(REF, said("Why does wasabi make eyes water"))
    assert ("your", "missing", None) in statuses(r)
    assert r.score == 86 and r.counts["missing"] == 1


def test_a_different_word_is_marked_wrong_with_what_was_heard():
    r = compare(REF, said("Why does wasabi make your ears water"))
    assert ("eyes", "wrong", "ears") in statuses(r)
    assert r.score == 86 and r.counts["wrong"] == 1  # 6 of 7 words spoken; the wrong one does not count


def test_wrong_word_does_not_count_towards_the_score():
    r = compare("one two three four", said("one two three five"))
    assert r.counts["wrong"] == 1 and r.score == 75


def test_extra_words_are_shown_but_do_not_hurt_the_score():
    r = compare("hello world", said("well hello there world"))
    assert [t.status for t in r.tokens] == ["extra", "ok", "extra", "ok"]
    assert r.score == 100


def test_low_recognition_confidence_marks_a_word_unclear_but_still_spoken():
    spoken = said("Why does wasabi make your eyes water")
    spoken[2] = Word("wasabi", 0.8, 1.2, 0.31)
    r = compare(REF, spoken)
    assert ("wasabi", "unclear", None) in statuses(r)
    assert r.score == 100 and r.counts["unclear"] == 1


def test_silence_or_nothing_recognised_marks_everything_missing():
    r = compare(REF, [])
    assert r.score == 0 and r.counts["missing"] == 7 and all(t.status == "missing" for t in r.tokens)


def test_unrelated_speech_pairs_words_in_order_then_reports_leftovers():
    r = compare("one two three", said("alpha beta"))
    assert statuses(r) == [("one", "wrong", "alpha"), ("two", "wrong", "beta"), ("three", "missing", None)]


def test_contractions_and_hyphens_compare_by_their_letters():
    assert compare("It's a 6,000-year-old pot.", said("its a 6000yearold pot")).score == 100


def test_reading_order_is_kept_for_mixed_errors():
    r = compare("the quick brown fox jumps", said("the brown fax jumps over"))
    assert statuses(r) == [
        ("the", "ok", None), ("quick", "missing", None), ("brown", "ok", None),
        ("fox", "wrong", "fax"), ("jumps", "ok", None), ("over", "extra", None),
    ]


def test_facts_summarise_the_differences_for_the_feedback_prompt():
    r = compare("one two three four five", said("one three fore five", prob=0.98))
    facts = r.facts()
    assert facts["missing"] == ["two"] and facts["wrong"] == [{"expected": "four", "heard": "fore"}]
    assert facts["unclear"] == [] and facts["extra"] == []


# ---- feedback sanitising ------------------------------------------------------------------


def test_advice_with_phonetic_symbols_or_mouth_positions_is_removed():
    data = {
        "summary": "整體不錯。eyes 的 /aɪ/ 雙元音要發清楚。請再練習。",
        "tips": ["放慢速度重念整句", "注意 ears 的 /ɜːr/ 音", "舌尖要碰到上排牙齒", "重聽原音"],
    }
    out = sanitize_feedback(data)
    assert out["summary"] == "整體不錯。請再練習。"
    assert out["tips"] == ["放慢速度重念整句", "重聽原音"]


def test_normal_advice_is_left_alone():
    data = {"summary": "你把 eyes 念成了 ears，兩個字聽起來很像。", "tips": ["重聽原音，注意 eyes 這個字"]}
    assert sanitize_feedback(data) == data


def test_slashes_in_ordinary_text_are_not_mistaken_for_phonetics():
    assert sanitize_feedback({"tips": ["用 and/or 這種寫法時也要留意連音"]})["tips"] == ["用 and/or 這種寫法時也要留意連音"]


def test_partial_feedback_with_missing_fields_is_handled():
    assert sanitize_feedback({}) == {}
    assert sanitize_feedback({"summary": "還在寫"}) == {"summary": "還在寫"}
    assert sanitize_feedback({"tips": []}) == {"tips": []}


def test_finished_feedback_always_has_at_least_one_suggestion():
    assert finish_feedback({"summary": "很好", "tips": ["注意 /ɪ/ 音"]})["tips"] == [FALLBACK_TIP]
    assert finish_feedback({"summary": "很好", "tips": ["放慢"]})["tips"] == ["放慢"]
