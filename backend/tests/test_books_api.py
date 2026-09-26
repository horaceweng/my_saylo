import json

import pytest
from ebooklib import epub

from app.config import settings
from app.models import Book, Chapter, Paragraph
from app.routers.books import get_translation_provider
from app.services import gutenberg
from app.services.gutenberg import GutenbergError
from app.services.llm import LLMError
from tests.test_books import make_epub, para

TEXT = "\n\n".join(f"CHAPTER {r}.\n\n{para()}\n\n{para(2)}" for r in ["I", "II", "III"])


def upload(client, name, data):
    return client.post("/api/books/upload", files={"file": (name, data, "application/octet-stream")})


@pytest.fixture
def env(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return client, session, tmp_path


def epub_bytes(tmp_path, n=2):
    docs = [(f"c{i}.xhtml", f"<h2>Chapter {i}</h2><p>{para()}</p><p>{para()}</p>") for i in range(1, n + 1)]
    return make_epub(tmp_path, docs, title="My Novel", author="Some Author").read_bytes()


def test_uploading_an_epub_saves_chapters_paragraphs_and_a_level(env):
    client, session, tmp = env
    res = upload(client, "novel.epub", epub_bytes(tmp))
    book = res.json()
    assert res.status_code == 200 and (book["title"], book["author"], book["source"]) == ("My Novel", "Some Author", "epub")
    assert book["chapter_count"] == 2 and book["paragraph_count"] == 4 and book["level"] in ("A2", "B1", "B2", "C1+") and book["word_count"] > 50
    assert len(session.exec(__import__("sqlmodel").select(Paragraph)).all()) == 4


def test_uploading_plain_text_splits_chapters(env):
    client, *_ = env
    book = upload(client, "my_story.txt", TEXT.encode()).json()
    assert book["source"] == "text" and book["chapter_count"] == 3 and book["title"] == "my story"
    detail = client.get(f"/api/books/{book['id']}").json()
    assert [c["title"] for c in detail["chapters"]] == ["CHAPTER I.", "CHAPTER II.", "CHAPTER III."]
    assert [c["first_paragraph"] for c in detail["chapters"]] == [0, 2, 4]


def test_the_same_file_is_not_added_twice(env):
    client, session, tmp = env
    data = epub_bytes(tmp)
    a, b = upload(client, "a.epub", data).json(), upload(client, "renamed.epub", data).json()
    assert a["id"] == b["id"] and len(client.get("/api/books").json()) == 1


def test_bad_uploads_are_refused_with_a_reason_and_leave_nothing_behind(env):
    client, session, _ = env
    assert upload(client, "notes.pdf", b"x").status_code == 400
    assert upload(client, "empty.txt", b"").status_code == 400
    res = upload(client, "broken.epub", b"this is not an epub")
    assert res.status_code == 400 and "無法讀取" in res.json()["detail"]
    assert upload(client, "blank.txt", b"   \n\n  ").status_code == 400
    assert client.get("/api/books").json() == []


def test_chapter_and_book_lookups(env):
    client, _, _ = env
    book = upload(client, "s.txt", TEXT.encode()).json()
    chapter = client.get(f"/api/books/{book['id']}/chapters/1").json()
    assert chapter["title"] == "CHAPTER II." and [p["idx"] for p in chapter["paragraphs"]] == [2, 3]
    assert chapter["paragraphs"][0]["translation"] == "" and chapter["paragraphs"][0]["text"].startswith("It was a bright cold day")
    assert client.get(f"/api/books/{book['id']}/chapters/9").status_code == 404
    assert client.get("/api/books/9999").status_code == 404


def test_list_can_be_filtered_by_level_and_rejects_an_unknown_one(env, session):
    client, *_ = env
    session.add_all([Book(title="Easy", level="A2", source_key="a"), Book(title="Hard", level="C1+", source_key="b")])
    session.commit()
    assert [b["title"] for b in client.get("/api/books", params={"level": "C1+"}).json()] == ["Hard"]
    assert len(client.get("/api/books").json()) == 2
    assert client.get("/api/books", params={"level": "Z9"}).status_code == 400


def test_reading_progress_is_saved_validated_and_shown_as_a_percentage(env):
    client, *_ = env
    book = upload(client, "s.txt", TEXT.encode()).json()
    assert client.put(f"/api/books/{book['id']}/progress", json={"chapter": 2, "paragraph": 4}).json() == {"ok": True}
    row = client.get("/api/books").json()[0]
    assert (row["last_chapter"], row["last_paragraph"], row["progress_percent"]) == (2, 4, 83)  # paragraph 5 of 6
    assert client.put(f"/api/books/{book['id']}/progress", json={"chapter": 9, "paragraph": 0}).status_code == 400
    assert client.put(f"/api/books/{book['id']}/progress", json={"chapter": 0, "paragraph": 99}).status_code == 400
    assert client.put("/api/books/9999/progress", json={"chapter": 0, "paragraph": 0}).status_code == 404


def test_deleting_a_book_removes_everything_that_belongs_to_it(env, session):
    client, *_ = env
    book = upload(client, "s.txt", TEXT.encode()).json()
    assert client.delete(f"/api/books/{book['id']}").json() == {"ok": True}
    sm = __import__("sqlmodel")
    assert session.exec(sm.select(sm.func.count()).select_from(Paragraph)).one() == 0
    assert session.exec(sm.select(sm.func.count()).select_from(Chapter)).one() == 0
    assert client.delete(f"/api/books/{book['id']}").status_code == 404


def test_search_and_gutenberg_import(env, monkeypatch, tmp_path):
    client, session, tmp = env
    monkeypatch.setattr(gutenberg, "search", lambda q: [{"id": 11, "title": "Alice", "author": "Carroll", "cover": "c"}])
    assert client.get("/api/books/search", params={"q": "alice"}).json()[0]["id"] == 11
    src = make_epub(tmp_path, [("c.xhtml", f"<h2>One</h2><p>{para()}</p><p>{para()}</p>")], title="Alice", author="Carroll", name="g.epub")
    monkeypatch.setattr(gutenberg, "download_epub", lambda book_id, dest, client=None: src)
    book = client.post("/api/books/gutenberg", json={"id": 11}).json()
    assert book["source"] == "gutenberg" and book["source_key"] == "gutenberg:11" and book["cover"].endswith("pg11.cover.medium.jpg")
    assert client.post("/api/books/gutenberg", json={"id": 11}).json()["id"] == book["id"]  # not downloaded again


def test_gutenberg_problems_become_readable_errors(env, monkeypatch):
    client, *_ = env

    def fail(*a, **k):
        raise GutenbergError("連不上 Project Gutenberg，請稍後再試")

    monkeypatch.setattr(gutenberg, "search", fail)
    monkeypatch.setattr(gutenberg, "download_epub", fail)
    assert "連不上" in client.get("/api/books/search", params={"q": "x"}).json()["detail"]
    assert client.post("/api/books/gutenberg", json={"id": 1}).status_code == 400
    assert client.get("/api/books/search").status_code == 422


# ---- translating a paragraph --------------------------------------------------------------


class FakeTranslator:
    calls = 0
    fail = False
    empty = False

    async def stream(self, system, user, *, json_mode=False):
        FakeTranslator.calls += 1
        if FakeTranslator.fail:
            raise LLMError("無法連線到 Ollama")
        if FakeTranslator.empty:
            yield "  "
            return
        for piece in ["那是明亮", "寒冷的", "四月天。"]:
            yield piece


def events(res):
    return [json.loads(line) for line in res.text.splitlines() if line]


def first_paragraph_id(client):
    book = upload(client, "s.txt", TEXT.encode()).json()
    return client.get(f"/api/books/{book['id']}/chapters/0").json()["paragraphs"][0]["id"], book["id"]


def test_a_paragraph_is_translated_as_a_stream_and_only_once(env):
    from app.main import app

    client, *_ = env
    FakeTranslator.calls, FakeTranslator.fail, FakeTranslator.empty = 0, False, False
    app.dependency_overrides[get_translation_provider] = lambda: FakeTranslator()
    pid, book_id = first_paragraph_id(client)
    got = events(client.post(f"/api/books/paragraphs/{pid}/translate/stream"))
    assert [e["type"] for e in got] == ["partial", "partial", "partial", "done"]
    assert [e["text"] for e in got] == ["那是明亮", "那是明亮寒冷的", "那是明亮寒冷的四月天。", "那是明亮寒冷的四月天。"]
    assert client.get(f"/api/books/{book_id}/chapters/0").json()["paragraphs"][0]["translation"] == "那是明亮寒冷的四月天。"
    again = events(client.post(f"/api/books/paragraphs/{pid}/translate/stream"))
    assert again == [{"type": "done", "text": "那是明亮寒冷的四月天。"}] and FakeTranslator.calls == 1


def test_translation_errors_are_reported_and_nothing_is_saved(env):
    from app.main import app

    client, *_ = env
    app.dependency_overrides[get_translation_provider] = lambda: FakeTranslator()
    pid, book_id = first_paragraph_id(client)
    FakeTranslator.fail, FakeTranslator.empty = True, False
    assert events(client.post(f"/api/books/paragraphs/{pid}/translate/stream"))[-1] == {"type": "error", "message": "無法連線到 Ollama"}
    FakeTranslator.fail, FakeTranslator.empty = False, True
    assert events(client.post(f"/api/books/paragraphs/{pid}/translate/stream"))[-1]["type"] == "error"
    assert client.get(f"/api/books/{book_id}/chapters/0").json()["paragraphs"][0]["translation"] == ""
    assert client.post("/api/books/paragraphs/9999/translate/stream").status_code == 404


def test_saved_books_are_graded_again_once_when_the_grading_method_changes():
    from sqlmodel import Session, SQLModel, create_engine, select
    from sqlmodel.pool import StaticPool

    from app.models import Setting
    from app.routers.books import regrade_all
    from app.services import grading

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        easy = Book(title="Easy", level="C1+", score=99.0, source_key="a")  # graded long ago with an old method
        s.add(easy)
        s.commit()
        chapter = Chapter(book_id=easy.id, idx=0, title="One", paragraph_count=1, word_count=12)
        s.add(chapter)
        s.commit()
        s.add(Paragraph(book_id=easy.id, chapter_id=chapter.id, idx=0, text="The cat sat on the mat. The dog ran to the park. We like to play."))
        s.commit()
    assert regrade_all(engine) == 1
    with Session(engine) as s:
        book = s.exec(select(Book)).one()
        assert book.level == "A2" and book.score < 12  # the old, wrong grade is gone
        assert s.get(Setting, "grading_version").value == grading.GRADING_VERSION
    assert regrade_all(engine) == 0  # up to date: nothing to do at the next start
    with Session(engine) as s:
        s.get(Setting, "grading_version").value = "0"  # as if the method had changed again
        book = s.exec(select(Book)).one()
        book.level = "B2"
        s.add(book)
        s.commit()
    assert regrade_all(engine) == 1
