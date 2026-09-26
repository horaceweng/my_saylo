import pytest

from app.config import settings
from app.services import dictionary

pytestmark = pytest.mark.skipif(not settings.dict_db_path.exists(), reason="dict.sqlite not built")


def test_lookup_returns_traditional_chinese():
    entry = dictionary.lookup("apple")
    assert entry is not None
    assert "蘋果" in entry.translation


def test_inflected_form_resolves_to_lemma():
    assert dictionary.lookup("went").word == "go"
    assert dictionary.lookup("children").word == "child"


def test_unknown_word():
    assert dictionary.lookup("zzzxqv") is None
    assert not dictionary.exists("zzzxqv")


def test_difficulty_levels_are_ordered():
    assert dictionary.lookup("the").level == 0
    assert dictionary.lookup("ubiquitous").level >= 3
    assert dictionary.lookup("ubiquitous").level > dictionary.lookup("house").level


def test_parse_exchange():
    assert dictionary.parse_exchange("p:went/d:gone/i:going") == {"p": "went", "d": "gone", "i": "going"}
    assert dictionary.parse_exchange("") == {}


def test_wrong_lemma_links_in_the_data_are_not_followed():
    for word in ["also", "of", "some", "they", "my", "his", "we"]:
        assert dictionary.lookup(word).word == word, word  # not "conjurer", "have", "an", "it", "i", "he"
    assert dictionary.lookup("could").word == "can" and dictionary.lookup("born").word == "bear" and dictionary.lookup("walked").word == "walk"


def test_a_word_takes_the_level_of_the_easiest_exam_list_it_is_on():
    level = dictionary.difficulty_level
    assert level([], 100) == 0 and level(["zk", "gk"], 100) == 0  # very common beats any tag
    assert level(["cet4", "toefl"], 3500) == 1 and level(["gk", "cet6", "toefl", "gre"], 3500) == 1
    assert level(["cet6", "toefl", "ielts"], 3500) == 2 and level(["ky"], 9000) == 2
    assert level(["toefl", "ielts", "gre"], 6000) == 3 and level(["toefl"], 14000) == 3
    assert level(["gre"], 20000) == 4
    assert [level([], f) for f in (5000, 15000, 30000, 0)] == [1, 2, 3, 4]  # no list: by how rare


def test_everyday_news_words_are_no_longer_marked_as_hard():
    for word, expected in [("strict", 1), ("behave", 1), ("sanctions", 2), ("compensation", 2), ("government", 0)]:
        assert dictionary.lookup(word).level == expected, word


def test_forms_that_declare_what_they_are_follow_their_base_word_and_frequent_words_are_not_rare():
    assert dictionary.lookup("were").word == "be" and dictionary.lookup("were").level == 0
    for word in ["an", "BBC", "were", "are", "is", "was", "been"]:
        assert dictionary.lookup(word).level <= 1, word
    assert dictionary.difficulty_level([], 0, 500) == 0 and dictionary.difficulty_level([], 0, 0) == 4  # BNC rank as a fallback
