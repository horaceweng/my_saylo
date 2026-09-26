from sqlmodel import select

from app.models import Media, Recording, Segment, Setting, Word
from app.services import resegment


def add_video(session, groups, status="ready"):
    """A video whose sentences were saved as `groups` (lists of (text, start, end)); the first group is one sentence."""
    media = Media(kind="video", source_url="u", external_id="x", title="t", status=status, transcribed=True)
    session.add(media)
    session.commit()
    for i, group in enumerate(groups):
        seg = Segment(media_id=media.id, idx=i, start=group[0][1], end=group[-1][2], text=" ".join(t for t, _, _ in group), translation=f"翻譯{i}")
        session.add(seg)
        session.flush()
        for j, (text, start, end) in enumerate(group):
            session.add(Word(segment_id=seg.id, idx=j, text=text, start=start, end=end))
    session.commit()
    return media


def words(text, t0=0.0):
    return [(tok, t0 + i * 0.3, t0 + i * 0.3 + 0.24) for i, tok in enumerate(text.split())]


def sentences_of(session, media_id):
    return [(s.idx, s.text, s.translation) for s in session.exec(select(Segment).where(Segment.media_id == media_id).order_by(Segment.idx)).all()]


def test_two_halves_of_one_sentence_are_joined_and_the_others_keep_their_translation(session):
    first = words("It was over.")
    half_a = words("Robin has a habit of stealing from the rich to give to the poor, but the sheriff, who takes money from the poor to fund", 5.0)
    half_b = words("his lavish lifestyle, can't stand him.", 5.0 + 25 * 0.3)
    last = words("The end.", 20.0)
    media = add_video(session, [first, half_a, half_b, last])
    assert resegment.resegment_media(session, media.id) == 1
    got = sentences_of(session, media.id)
    assert [g[0] for g in got] == [0, 1, 2]
    assert got[0][2] == "翻譯0" and got[2][2] == "翻譯3"  # untouched sentences keep their translations
    assert got[1][1].startswith("Robin has") and got[1][1].endswith("can't stand him.") and got[1][2] == ""  # the joined one is translated again
    assert len(session.exec(select(Word)).all()) == len(first) + len(half_a) + len(half_b) + len(last)  # no word is lost
    joined = session.exec(select(Segment).where(Segment.idx == 1)).one()
    assert [w.idx for w in session.exec(select(Word).where(Word.segment_id == joined.id).order_by(Word.idx)).all()] == list(range(len(half_a) + len(half_b)))


def test_nothing_changes_when_the_sentences_are_already_right(session):
    media = add_video(session, [words("Hello there."), words("How are you?", 3.0)])
    assert resegment.resegment_media(session, media.id) == 0
    assert [g[2] for g in sentences_of(session, media.id)] == ["翻譯0", "翻譯1"]


def test_a_shadowing_attempt_moves_to_the_sentence_that_now_holds_its_beginning(session):
    half_a = words("He thinks of him as a robber and wants to have him arrested on his wedding day of all days, just as he is about", 0.0)
    half_b = words("to marry the beautiful Maid Marian.", 25 * 0.3)
    media = add_video(session, [half_a, half_b])
    old_second = session.exec(select(Segment).where(Segment.idx == 1)).one()
    session.add(Recording(segment_id=old_second.id, heard_text="to marry"))
    session.commit()
    resegment.resegment_media(session, media.id)
    joined = session.exec(select(Segment)).one()
    rec = session.exec(select(Recording)).one()
    assert rec.segment_id == joined.id  # not left pointing at a sentence that no longer exists


def test_a_sentence_that_ended_with_a_closing_quote_is_split_now(session):
    text = words('"and what is the use of a book?" thought Alice. Then she left.')
    media = add_video(session, [text])
    assert resegment.resegment_media(session, media.id) == 2
    assert [g[1] for g in sentences_of(session, media.id)] == ['"and what is the use of a book?" thought Alice.', "Then she left."]


def test_resegment_all_runs_once_marks_changed_videos_for_translation_and_skips_unfinished_ones(session):
    engine = session.get_bind()
    fixed = add_video(session, [words("Hello there."), words("Fine.", 3.0)])
    broken = add_video(session, [words("One two three, but the"), words("sheriff came.", 1.5)])
    busy = add_video(session, [words("Still busy, but the"), words("work goes on.", 1.5)], status="transcribing")
    assert resegment.resegment_all(engine) == [broken.id]
    for m in (fixed, broken, busy):
        session.refresh(m)
    assert (fixed.status, broken.status, busy.status) == ("ready", "translating", "transcribing")
    assert session.get(Setting, "segmentation_version").value == resegment.SEGMENTATION_VERSION
    assert resegment.resegment_all(engine) == []  # once per version
