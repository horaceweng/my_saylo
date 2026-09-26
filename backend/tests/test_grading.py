import pytest

from app.config import settings
from app.services import grading

pytestmark = pytest.mark.skipif(not settings.dict_db_path.exists(), reason="dict.sqlite not built")

EASY = "The cat sat on the mat. The dog ran to the park. We like to play. It is a good day. She has a red ball."
HARD = (
    "The ubiquitous ephemerality of quotidian obligations notwithstanding, the philosopher's sagacious disquisition "
    "elucidated inscrutable epistemological conundrums with surpassing perspicacity."
)


def test_simple_text_scores_lower_than_dense_text():
    easy, hard = grading.analyze([EASY]), grading.analyze([HARD])
    assert easy.hard_ratio < 0.05 < hard.hard_ratio
    assert grading.score(easy) < grading.score(hard)
    assert grading.grade([EASY])[0] in ("A2", "B1") and grading.grade([HARD * 3])[0] == "C1+"


def test_long_sentences_raise_the_score_even_with_the_same_words():
    short = " ".join(["The cat sat on the mat."] * 10)
    long = "The cat sat on the mat and the dog ran to the park and we like to play and it is a good day and she has a red ball."
    assert grading.analyze([long]).avg_sentence_words > grading.analyze([short]).avg_sentence_words * 2
    assert grading.score(grading.analyze([long])) > grading.score(grading.analyze([short]))


def test_names_in_the_middle_of_a_sentence_and_unknown_words_are_not_counted_as_hard():
    with_names = grading.analyze(["Yesterday Zxqvbnm and Bartholomew Quillfeather went home. It was a good day."])
    plain = grading.analyze(["Yesterday they went home. It was a good day."])
    assert with_names.hard_ratio == pytest.approx(plain.hard_ratio, abs=0.05)


def test_sentence_counting_ignores_abbreviations_and_empty_input():
    m = grading.analyze(["Mr. Smith met Dr. Jones. They talked."])
    assert m.sentences == 2
    empty = grading.analyze([])
    assert (empty.words, empty.sentences, empty.hard_ratio) == (0, 0, 0.0)
    assert grading.grade([])[0] == "A2"


def test_levels_follow_the_calibrated_thresholds():
    assert [grading.cefr_level(v) for v in (5, 11.9, 12.0, 14.9, 15.0, 18.4, 18.5, 40)] == ["A2", "A2", "B1", "B1", "B2", "B2", "C1+", "C1+"]
