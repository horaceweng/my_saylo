"""Cut the sentences of videos that are already saved again with the current rules (see segmenter.py).

The words and their times are kept; only the grouping into sentences changes. A sentence that stays as it is
keeps its translation; a new one is translated again."""

from sqlmodel import Session, col, select

from app.models import Media, Recording, Segment, Setting, Word
from app.services.segmenter import Word as TimedWord
from app.services.segmenter import split_sentences

SEGMENTATION_VERSION = "2"


def resegment_media(session: Session, media_id: int) -> int:
    """Regroup one video's words into sentences. Returns how many sentences are new (0 = nothing changed)."""
    old = session.exec(select(Segment).where(Segment.media_id == media_id).order_by(Segment.idx)).all()
    rows_of: dict[int, list[Word]] = {}
    for seg in old:
        rows_of[seg.id] = list(session.exec(select(Word).where(Word.segment_id == seg.id).order_by(Word.idx)).all())
    ordered = [row for seg in old for row in rows_of[seg.id]]
    if not ordered:
        return 0
    by_object: dict[int, Word] = {}
    timed: list[TimedWord] = []
    for row in ordered:
        item = TimedWord(row.text, row.start, row.end, row.prob)
        by_object[id(item)] = row
        timed.append(item)
    sentences = split_sentences(timed)

    old_by_words = {frozenset(w.id for w in rows_of[s.id]): s for s in old}
    kept: dict[int, Segment] = {}  # old segment id → itself, for those that stay exactly as they are
    new_segments: list[Segment] = []
    created = 0
    for idx, sentence in enumerate(sentences):
        rows = [by_object[id(w)] for w in sentence.words]
        same = old_by_words.get(frozenset(r.id for r in rows))
        if same is not None:
            same.idx = idx
            session.add(same)
            kept[same.id] = same
            new_segments.append(same)
            continue
        seg = Segment(media_id=media_id, idx=idx, start=sentence.start, end=sentence.end, text=sentence.text)
        session.add(seg)
        session.flush()
        for j, row in enumerate(rows):
            row.segment_id, row.idx = seg.id, j
            session.add(row)
        new_segments.append(seg)
        created += 1
    if created == 0 and len(kept) == len(old):
        session.rollback()
        return 0

    # a shadowing attempt belongs to the new sentence that now holds its old sentence's beginning
    for seg in old:
        if seg.id in kept:
            continue
        home = next((n for n in new_segments if n.start - 0.05 <= seg.start < n.end), None) or min(new_segments, key=lambda n: abs(n.start - seg.start))
        for rec in session.exec(select(Recording).where(Recording.segment_id == seg.id)).all():
            rec.segment_id = home.id
            session.add(rec)
    session.flush()
    for seg in old:
        if seg.id not in kept:
            session.delete(seg)
    session.commit()
    return created


def resegment_all(engine) -> list[int]:
    """Do it for every finished video, once per change of the rules. Videos that got new sentences are marked
    for translation (the caller queues them). Returns their ids."""
    with Session(engine) as session:
        marker = session.get(Setting, "segmentation_version")
        if marker and marker.value == SEGMENTATION_VERSION:
            return []
        changed: list[int] = []
        for media in session.exec(select(Media).where(Media.status == "ready").order_by(col(Media.id))).all():
            if resegment_media(session, media.id):
                media = session.get(Media, media.id)
                media.status, media.progress, media.error = "translating", 50, ""
                session.add(media)
                session.commit()
                changed.append(media.id)
        session.merge(Setting(key="segmentation_version", value=SEGMENTATION_VERSION))
        session.commit()
        return changed
