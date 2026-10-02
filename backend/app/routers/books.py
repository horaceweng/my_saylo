import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, col, delete, func, select

from app.config import settings
from app.db import get_session
from app.deps import admin_user, current_user
from app.models import Book, Chapter, Paragraph, Setting, User
from app.services import books, gutenberg, grading, prompts
from app.services.books import BookError, ParsedBook
from app.services.gutenberg import GutenbergError
from app.services.llm import LLMError, make_provider

router = APIRouter(prefix="/api/books", tags=["books"])

MAX_UPLOAD_BYTES = 60 * 1024 * 1024
LEVELS = ("A2", "B1", "B2", "C1+")


def get_translation_provider():
    return make_provider()


class GutenbergRequest(BaseModel):
    id: int


class Progress(BaseModel):
    chapter: int
    paragraph: int


def book_out(book: Book) -> dict:
    percent = round(100 * (book.last_paragraph + 1) / book.paragraph_count) if book.paragraph_count and book.last_paragraph else 0
    return {**book.model_dump(), "progress_percent": min(100, percent)}


def store_book(
    session: Session, parsed: ParsedBook, source: str, source_key: str, cover: str = "", url: str = "", published: str = "", site: str = "",
    added_by: int | None = None,
) -> Book:
    """Grade the book and save it with its chapters and paragraphs."""
    paragraphs = [p for chapter in parsed.chapters for p in chapter.paragraphs]
    level, score, metrics = grading.grade(paragraphs)
    book = Book(
        title=parsed.title, author=parsed.author, source=source, source_key=source_key, cover=cover, level=level,
        score=score, word_count=metrics.words, paragraph_count=len(paragraphs), chapter_count=len(parsed.chapters),
        url=url, published=published, site=site, added_by=added_by,
    )
    session.add(book)
    session.flush()
    index = 0
    for chapter_index, chapter in enumerate(parsed.chapters):
        row = Chapter(book_id=book.id, idx=chapter_index, title=chapter.title, paragraph_count=len(chapter.paragraphs), word_count=chapter.words)
        session.add(row)
        session.flush()
        for text in chapter.paragraphs:
            session.add(Paragraph(book_id=book.id, chapter_id=row.id, idx=index, text=text))
            index += 1
    session.commit()
    session.refresh(book)
    return book


def regrade_all(engine) -> int:
    """Grade every saved book and article again when the grading method has changed since they were graded.
    Returns how many were updated (0 when everything is up to date)."""
    with Session(engine) as session:
        marker = session.get(Setting, "grading_version")
        if marker and marker.value == grading.GRADING_VERSION:
            return 0
        updated = 0
        for book in session.exec(select(Book)).all():
            texts = session.exec(select(Paragraph.text).where(Paragraph.book_id == book.id).order_by(Paragraph.idx)).all()
            level, score, _ = grading.grade(texts)
            if (book.level, book.score) != (level, score):
                book.level, book.score = level, score
                session.add(book)
                updated += 1
        session.merge(Setting(key="grading_version", value=grading.GRADING_VERSION))
        session.commit()
        return updated


def _existing(session: Session, source_key: str) -> Book | None:
    return session.exec(select(Book).where(Book.source_key == source_key)).first()


@router.get("")
def list_books(level: str | None = None, kind: str = "book", session: Session = Depends(get_session)):
    """`kind=book` (default): books; `kind=news`: saved news articles, which are stored the same way."""
    stmt = select(Book).order_by(col(Book.created_at).desc())
    stmt = stmt.where(Book.source == "news") if kind == "news" else stmt.where(Book.source != "news")
    if level:
        if level not in LEVELS:
            raise HTTPException(400, f"等級必須是 {'、'.join(LEVELS)}")
        stmt = stmt.where(Book.level == level)
    return [book_out(b) for b in session.exec(stmt).all()]


@router.get("/search")
async def search_gutenberg(q: str):
    try:
        return await asyncio.to_thread(gutenberg.search, q)
    except GutenbergError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/gutenberg")
async def add_from_gutenberg(body: GutenbergRequest, session: Session = Depends(get_session), user: User = Depends(current_user)):
    key = f"gutenberg:{body.id}"
    if found := _existing(session, key):
        return book_out(found)
    bind, user_id = session.get_bind(), user.id

    def work() -> Book:
        with tempfile.TemporaryDirectory() as tmp:
            path = gutenberg.download_epub(body.id, Path(tmp))
            parsed = books.parse_epub(path)
        with Session(bind) as s:
            return store_book(s, parsed, "gutenberg", key, gutenberg.cover_url(body.id), added_by=user_id)

    try:
        return book_out(await asyncio.to_thread(work))
    except (GutenbergError, BookError) as e:
        raise HTTPException(400, str(e)) from e


@router.post("/upload")
async def upload_book(file: UploadFile, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """An EPUB or a plain-text file from the learner's computer."""
    name = file.filename or "book"
    ext = Path(name).suffix.lower()
    if ext not in (".epub", ".txt"):
        raise HTTPException(400, "請選擇 EPUB 或 txt 檔案")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(400, "檔案是空的")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "檔案太大（超過 60 MB）")
    key = f"sha1:{hashlib.sha1(data).hexdigest()}"
    if found := _existing(session, key):
        return book_out(found)
    bind, user_id = session.get_bind(), user.id

    def work() -> Book:
        if ext == ".epub":
            with tempfile.NamedTemporaryFile(suffix=".epub", dir=settings.data_dir) as tmp:
                tmp.write(data)
                tmp.flush()
                parsed = books.parse_epub(Path(tmp.name))
            source = "epub"
        else:
            text = data.decode("utf-8-sig", errors="replace")
            parsed = books.parse_text(text, fallback_title=Path(name).stem.replace("_", " "))
            source = "text"
        with Session(bind) as s:
            return store_book(s, parsed, source, key, added_by=user_id)

    try:
        return book_out(await asyncio.to_thread(work))
    except BookError as e:
        raise HTTPException(400, str(e)) from e


def _book(session: Session, book_id: int) -> Book:
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(404, "找不到這本書")
    return book


@router.get("/{book_id}")
def get_book(book_id: int, session: Session = Depends(get_session)):
    book = _book(session, book_id)
    chapters = session.exec(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.idx)).all()
    first_index, chapter_starts = 0, []
    for chapter in chapters:
        chapter_starts.append(first_index)
        first_index += chapter.paragraph_count
    return {
        **book_out(book),
        "chapters": [
            {"idx": c.idx, "title": c.title, "paragraph_count": c.paragraph_count, "word_count": c.word_count, "first_paragraph": start}
            for c, start in zip(chapters, chapter_starts)
        ],
    }


@router.get("/{book_id}/chapters/{chapter_idx}")
def get_chapter(book_id: int, chapter_idx: int, session: Session = Depends(get_session)):
    chapter = session.exec(select(Chapter).where(Chapter.book_id == book_id, Chapter.idx == chapter_idx)).first()
    if not chapter:
        raise HTTPException(404, "找不到這個章節")
    rows = session.exec(select(Paragraph).where(Paragraph.chapter_id == chapter.id).order_by(Paragraph.idx)).all()
    return {
        "idx": chapter.idx, "title": chapter.title,
        "paragraphs": [{"id": p.id, "idx": p.idx, "text": p.text, "translation": p.translation} for p in rows],
    }


@router.put("/{book_id}/progress")
def save_progress(book_id: int, body: Progress, session: Session = Depends(get_session)):
    book = _book(session, book_id)
    if not 0 <= body.chapter < book.chapter_count or not 0 <= body.paragraph < max(1, book.paragraph_count):
        raise HTTPException(400, "閱讀位置不正確")
    book.last_chapter, book.last_paragraph = body.chapter, body.paragraph
    session.add(book)
    session.commit()
    return {"ok": True}


@router.delete("/{book_id}")
def delete_book(book_id: int, session: Session = Depends(get_session), _: User = Depends(admin_user)):
    _book(session, book_id)
    session.exec(delete(Paragraph).where(Paragraph.book_id == book_id))
    session.exec(delete(Chapter).where(Chapter.book_id == book_id))
    session.exec(delete(Book).where(Book.id == book_id))
    session.commit()
    return {"ok": True}


@router.post("/paragraphs/{paragraph_id}/translate/stream")
async def translate_paragraph(paragraph_id: int, session: Session = Depends(get_session), provider=Depends(get_translation_provider)):
    """Translate one paragraph, streamed as newline-delimited JSON ({"type":"partial","text":…} … "done").
    The result is kept, so each paragraph is only ever translated once."""
    row = session.get(Paragraph, paragraph_id)
    if not row:
        raise HTTPException(404, "找不到這個段落")
    bind, text, saved = session.get_bind(), row.text, row.translation

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    async def events():
        if saved:
            yield line({"type": "done", "text": saved})
            return
        translated = ""
        try:
            async for chunk in provider.stream(prompts.PARAGRAPH_TRANSLATE_SYSTEM, text):
                translated += chunk
                yield line({"type": "partial", "text": translated.strip()})
        except LLMError as e:
            yield line({"type": "error", "message": str(e)})
            return
        final = translated.strip()
        if not final:
            yield line({"type": "error", "message": "模型沒有回傳翻譯，請再試一次"})
            return
        with Session(bind) as s:
            target = s.get(Paragraph, paragraph_id)
            if target:
                target.translation = final
                s.add(target)
                s.commit()
        yield line({"type": "done", "text": final})

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
