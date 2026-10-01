from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models import Media, Segment, Setting
from app.routers.media import regrade_media
from app.services import grading


def make_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def test_finished_media_is_graded_and_only_regraded_when_the_method_changes():
    engine = make_engine()
    with Session(engine) as s:
        easy = Media(kind="video", source_url="u", external_id="x", title="Easy", status="ready", level="C1+", score=99.0)
        s.add(easy)
        s.commit()
        easy_id = easy.id
        s.add(Segment(media_id=easy_id, idx=0, start=0, end=1, text="The cat sat on the mat."))
        s.add(Segment(media_id=easy_id, idx=1, start=1, end=2, text="We like to play."))
        # a video still being processed is never graded: there is no full transcript to judge yet
        busy = Media(kind="video", source_url="u2", external_id="y", title="Busy", status="translating")
        s.add(busy)
        s.commit()
        busy_id = busy.id

    assert regrade_media(engine) == 1
    with Session(engine) as s:
        media = s.exec(select(Media).where(Media.id == easy_id)).one()
        assert media.level == "A2" and media.score < 12  # the old, wrong grade is gone
        assert s.exec(select(Media).where(Media.id == busy_id)).one().level == ""
        assert s.get(Setting, "media_grading_version").value == grading.GRADING_VERSION

    assert regrade_media(engine) == 0  # up to date: nothing to do at the next start

    with Session(engine) as s:
        s.get(Setting, "media_grading_version").value = "0"  # as if the method had changed again
        media = s.exec(select(Media).where(Media.id == easy_id)).one()
        media.level = "B2"
        s.add(media)
        s.commit()
    assert regrade_media(engine) == 1


def test_grading_media_and_books_are_tracked_separately(session):
    from app.models import Book

    session.add(Media(kind="video", source_url="u", external_id="x", title="M", status="ready"))
    session.add(Book(title="B", source_key="k"))
    session.commit()
    # marking the book side done must not make the media side think it is already done
    session.merge(Setting(key="grading_version", value=grading.GRADING_VERSION))
    session.commit()
    assert regrade_media(session.get_bind()) == 1
