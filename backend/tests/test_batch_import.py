import pytest
from sqlmodel import select

from app.models import Media, Segment, Word
from app.services.batch_import import BatchImportError, import_item, parse_item

VIDEO = {
    "kind": "video",
    "source_url": "https://www.youtube.com/watch?v=abc12345678",
    "title": "Introducing Let's Learn English",
    "duration": 34.0,
    "segments": [
        {"text": "Hello there.", "start": 0.0, "end": 1.2, "translation": "哈囉。",
         "words": [{"text": "Hello", "start": 0.0, "end": 0.5, "prob": 0.98}, {"text": "there.", "start": 0.6, "end": 1.2, "prob": 0.95}]},
        {"text": "Welcome to the lesson.", "start": 1.4, "end": 3.0, "translation": "歡迎來上課。", "words": []},
    ],
}

PODCAST = {
    "kind": "podcast",
    "source_url": "https://learningenglish.voanews.com/a/8007217/audio.mp3",
    "title": "Containers for Planting Seeds",
    "segments": [{"text": "It rained all day.", "start": 0.0, "end": 2.0, "translation": "下了一整天的雨。", "words": []}],
}


def test_a_video_is_imported_with_its_sentences_and_words(session):
    item = parse_item(VIDEO)
    media = import_item(session, item)
    assert media is not None and media.kind == "video" and media.status == "ready" and media.progress == 100
    assert media.transcribed is True and media.duration == 34.0
    assert media.external_id == "abc12345678"  # the real YouTube video id, not a hash
    assert media.thumbnail == "https://i.ytimg.com/vi/abc12345678/hqdefault.jpg"
    segments = session.exec(select(Segment).where(Segment.media_id == media.id).order_by(Segment.idx)).all()
    assert [s.text for s in segments] == ["Hello there.", "Welcome to the lesson."]
    assert [s.translation for s in segments] == ["哈囉。", "歡迎來上課。"]
    words = session.exec(select(Word).where(Word.segment_id == segments[0].id).order_by(Word.idx)).all()
    assert [(w.text, w.idx) for w in words] == [("Hello", 0), ("there.", 1)]
    assert session.exec(select(Word).where(Word.segment_id == segments[1].id)).all() == []  # the second sentence gave no words, and that is fine


def test_a_podcast_episode_gets_a_stable_hash_id_like_a_hand_added_one(session):
    import hashlib

    media = import_item(session, parse_item(PODCAST))
    assert media.kind == "podcast" and media.external_id == hashlib.sha1(PODCAST["source_url"].encode()).hexdigest()[:11]
    assert media.thumbnail == ""  # no thumbnail was given and it is not a video link
    assert media.duration == 2.0  # missing duration falls back to the last sentence's end


def test_importing_the_same_link_twice_does_nothing_the_second_time(session):
    first = import_item(session, parse_item(VIDEO))
    again = import_item(session, parse_item(VIDEO))
    assert again is None
    assert len(session.exec(select(Media)).all()) == 1
    assert len(session.exec(select(Segment)).all()) == 2  # not duplicated


def test_a_podcast_using_the_same_link_as_an_existing_video_is_not_treated_as_a_duplicate(session):
    # duplicates are matched by (kind, link): a podcast never gets skipped because of a video at the same URL
    video = import_item(session, parse_item(VIDEO))
    podcast = import_item(session, parse_item({**PODCAST, "source_url": VIDEO["source_url"]}))
    assert video is not None and podcast is not None and podcast.id != video.id
    assert len(session.exec(select(Media)).all()) == 2


@pytest.mark.parametrize("broken,message", [
    ({k: v for k, v in VIDEO.items() if k != "segments"}, "segments"),
    ({**VIDEO, "kind": "audio"}, "不支援"),
    ({**VIDEO, "source_url": ""}, "source_url"),
    ({**VIDEO, "segments": [{"text": "x", "start": 1.0, "end": 0.5}]}, "結束時間"),
    ({**VIDEO, "segments": [{"text": "x", "start": 0.0}]}, "不完整"),
])
def test_broken_result_data_is_refused_with_a_reason(broken, message):
    with pytest.raises(BatchImportError, match=message):
        parse_item(broken)


def test_an_item_with_no_sentences_at_all_is_refused(session):
    with pytest.raises(BatchImportError, match="沒有任何句子"):
        import_item(session, parse_item({**VIDEO, "segments": []}))
    assert session.exec(select(Media)).all() == []


def test_a_missing_title_gets_a_placeholder_rather_than_being_blank(session):
    media = import_item(session, parse_item({**PODCAST, "title": ""}))
    assert media.title and media.title != ""


def test_imported_media_is_graded_like_a_book(session):
    from app.services.grading import grade as compute_grade

    easy = {**VIDEO, "segments": [{"text": "The cat sat on the mat.", "start": 0.0, "end": 2.0}]}
    hard = {**PODCAST, "source_url": "https://a.com/hard.mp3",
            "segments": [{"text": "Notwithstanding the ostensibly perfunctory adjudication, the plaintiff's counsel remained circumspect.", "start": 0.0, "end": 5.0}]}
    easy_media = import_item(session, parse_item(easy))
    hard_media = import_item(session, parse_item(hard))
    assert easy_media.level == compute_grade(["The cat sat on the mat."])[0]
    assert hard_media.score > easy_media.score
