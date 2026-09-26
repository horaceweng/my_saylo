from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Media(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str = "video"  # video | podcast
    source_url: str
    external_id: str = Field(default="", index=True)  # YouTube video id
    title: str = ""
    thumbnail: str = ""
    audio_path: str = ""
    duration: float = 0
    status: str = "pending"  # pending | downloading | transcribing | translating | ready | error
    progress: int = 0  # 0-100
    error: str = ""
    transcribed: bool = False  # every part of the audio has been turned into sentences
    created_at: datetime = Field(default_factory=_now)


class Segment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    media_id: int = Field(foreign_key="media.id", index=True)
    idx: int
    start: float
    end: float
    text: str
    translation: str = ""


class Word(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    segment_id: int = Field(foreign_key="segment.id", index=True)
    idx: int
    text: str
    start: float
    end: float
    prob: float = 1.0


class SavedPhrase(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    text: str
    context_sentence: str = ""
    translation: str = ""
    note: str = ""
    source_kind: str = "video"
    source_id: int | None = None
    timestamp: float = 0
    created_at: datetime = Field(default_factory=_now)
    # spaced review (see services/srs.py)
    due_at: datetime = Field(default_factory=_now, index=True)
    interval_days: float = 0.0
    ease: float = 2.5
    reps: int = 0
    lapses: int = 0


class AiCache(SQLModel, table=True):
    key: str = Field(primary_key=True)
    kind: str
    payload_json: str
    created_at: datetime = Field(default_factory=_now)


class Recording(SQLModel, table=True):
    """One shadowing attempt: what the learner said for one sentence, and how it compared."""

    id: int | None = Field(default=None, primary_key=True)
    segment_id: int = Field(foreign_key="segment.id", index=True)
    file_path: str = ""  # 16 kHz mono wav
    duration: float = 0
    heard_text: str = ""  # what speech recognition heard
    score: int = 0  # percentage of the sentence's words that were spoken
    diff_json: str = "[]"  # word-by-word comparison, see services/shadowing.py
    feedback_json: str = ""  # the AI's comments, filled in on request
    created_at: datetime = Field(default_factory=_now)


class Book(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author: str = ""
    source: str = "epub"  # epub | text | gutenberg | news (an article is stored as a one-chapter book)
    source_key: str = Field(default="", index=True)  # "gutenberg:11" or "sha1:…": the same book is not added twice
    cover: str = ""
    level: str = ""  # A2 | B1 | B2 | C1+ (an estimate, see services/grading.py)
    score: float = 0.0
    word_count: int = 0
    paragraph_count: int = 0
    chapter_count: int = 0
    url: str = ""  # the original page, for a news article
    published: str = ""  # YYYY-MM-DD
    site: str = ""  # "BBC News", "VOA Learning English" …
    last_chapter: int = 0  # reading position: chapter index …
    last_paragraph: int = 0  # … and the paragraph's index within the whole book
    created_at: datetime = Field(default_factory=_now)


class Chapter(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(foreign_key="book.id", index=True)
    idx: int
    title: str
    paragraph_count: int = 0
    word_count: int = 0


class Paragraph(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(foreign_key="book.id", index=True)
    chapter_id: int = Field(foreign_key="chapter.id", index=True)
    idx: int  # position in the whole book, from 0
    text: str
    translation: str = ""


class Feed(SQLModel, table=True):
    """A feed the learner follows: news articles or a podcast's episodes (`kind`)."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(default="news", index=True)  # news | podcast
    url: str = Field(index=True)
    title: str
    image: str = ""
    created_at: datetime = Field(default_factory=_now)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""
