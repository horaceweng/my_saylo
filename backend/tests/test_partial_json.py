import json

from app.services.partial_json import parse_partial

DOC = {
    "translation": "讓我們退一步",
    "structure": "Let's + 動詞",
    "grammar_points": [{"point": "Let's", "explanation": "縮寫 \"Let us\""}, {"point": "back up", "explanation": "退後"}],
    "similar_examples": [{"en": "Let's go.", "zh": "走吧"}],
}
TEXT = json.dumps(DOC, ensure_ascii=False)


def test_complete_document_round_trips():
    assert parse_partial(TEXT) == DOC


def test_every_prefix_parses_or_returns_none_and_never_raises():
    for n in range(len(TEXT) + 1):
        result = parse_partial(TEXT[:n])
        assert result is None or isinstance(result, dict)


def test_partial_string_value_is_kept():
    assert parse_partial('{"translation": "讓我們退') == {"translation": "讓我們退"}


def test_half_written_key_is_dropped():
    assert parse_partial('{"translation": "x", "stru') == {"translation": "x"}
    assert parse_partial('{"translation":') == {}


def test_partial_array_item_keeps_finished_items_only():
    text = '{"grammar_points": [{"point": "a", "explanation": "b"}, {"po'
    assert parse_partial(text) == {"grammar_points": [{"point": "a", "explanation": "b"}]}


def test_partial_item_with_some_fields_is_kept():
    text = '{"grammar_points": [{"point": "a", "explanation": "b"}, {"point": "c", "explan'
    assert parse_partial(text)["grammar_points"][-1] == {"point": "c"}


def test_escape_at_the_cut_does_not_break():
    assert parse_partial('{"a": "quote \\') == {"a": "quote "}
    assert parse_partial('{"a": "x \\"y') == {"a": 'x "y'}


def test_growth_is_monotonic_for_top_level_strings():
    seen = ""
    for n in range(len(TEXT) + 1):
        got = (parse_partial(TEXT[:n]) or {}).get("translation", "")
        assert got.startswith(seen)
        seen = got


def test_not_json_yet():
    assert parse_partial("") is None
    assert parse_partial("hello") is None
