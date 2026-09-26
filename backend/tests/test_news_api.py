import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app import db as db_module
from app.models import Book, Feed, Setting
from app.routers import news as news_router
from app.services import news
from app.services.news import Article, FeedItem, NewsError
from tests.test_news import BODY


@pytest.fixture
def env(client, session, monkeypatch):
    return client, session, monkeypatch


def fake_article(url="https://www.example.com/news/wage"):
    return Article("Minimum wage to rise", "Jane Reporter", "2026-09-24", "Example News", "https://img.example.com/w.jpg", url, list(BODY))


def test_feeds_can_be_added_listed_and_removed_and_a_bad_link_is_refused(env):
    client, session, monkeypatch = env
    monkeypatch.setattr(news, "read_feed", lambda url: ("Example Feed", [FeedItem("Story", "https://a.com/1")]))
    feed = client.post("/api/news/feeds", json={"url": "https://a.com/rss"}).json()
    assert feed["title"] == "Example Feed" and client.post("/api/news/feeds", json={"url": "https://a.com/rss"}).json()["id"] == feed["id"]
    assert [f["title"] for f in client.get("/api/news/feeds").json()] == ["Example Feed"]

    def bad(url):
        raise NewsError("這不是有效的 RSS／Atom 訂閱，或裡面沒有文章")

    monkeypatch.setattr(news, "read_feed", bad)
    res = client.post("/api/news/feeds", json={"url": "https://a.com/page"})
    assert res.status_code == 400 and "不是有效的 RSS" in res.json()["detail"]
    assert client.post("/api/news/feeds", json={"url": "hello"}).status_code == 400
    assert client.delete(f"/api/news/feeds/{feed['id']}").json() == {"ok": True}
    assert client.delete(f"/api/news/feeds/{feed['id']}").status_code == 404
    assert client.get("/api/news/feeds").json() == []


def test_default_feeds_are_added_once_and_stay_deleted(env, monkeypatch):
    client, session, _ = env
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(news_router, "engine", engine)
    news_router.ensure_default_feeds()
    with Session(engine) as s:
        feeds = s.exec(select(Feed)).all()
        assert len(feeds) == len(news.DEFAULT_FEEDS) and any("BBC" in f.title for f in feeds) and any("VOA" in f.title for f in feeds)
        for f in feeds:
            s.delete(f)
        s.commit()
    news_router.ensure_default_feeds()  # runs again on the next start: must not bring them back
    with Session(engine) as s:
        assert s.exec(select(Feed)).all() == [] and s.get(Setting, "default_feeds_added").value == "1"


def test_feed_items_show_which_articles_are_already_saved_with_their_level(env):
    client, session, monkeypatch = env
    feed = Feed(title="F", url="https://a.com/rss")
    session.add(feed)
    session.add(Book(title="Saved", source="news", source_key=news.url_key("https://a.com/1"), level="B2"))
    session.commit()
    monkeypatch.setattr(news, "read_feed", lambda url: ("F", [FeedItem("One", "https://a.com/1?utm_source=rss", "2026-09-24", "s"), FeedItem("Two", "https://a.com/2")]))
    items = client.get(f"/api/news/feeds/{feed.id}/items").json()
    assert [(i["title"], i["level"], i["article_id"] is not None) for i in items] == [("One", "B2", True), ("Two", "", False)]
    assert client.get("/api/news/feeds/9999/items").status_code == 404

    def down(url):
        raise NewsError("連不上這個網址")

    monkeypatch.setattr(news, "read_feed", down)
    assert client.get(f"/api/news/feeds/{feed.id}/items").status_code == 502


def test_adding_an_article_stores_it_as_a_one_chapter_news_book_with_a_level(env):
    client, session, monkeypatch = env
    monkeypatch.setattr(news, "read_article", lambda url, client=None: fake_article())
    book = client.post("/api/news/articles", json={"url": "https://www.example.com/news/wage?utm_source=x"}).json()
    assert (book["source"], book["title"], book["site"], book["published"]) == ("news", "Minimum wage to rise", "Example News", "2026-09-24")
    assert book["chapter_count"] == 1 and book["paragraph_count"] == 4 and book["level"] in ("A2", "B1", "B2", "C1+")
    assert book["cover"] == "https://img.example.com/w.jpg" and book["url"].startswith("https://www.example.com/news/wage")
    chapter = client.get(f"/api/books/{book['id']}/chapters/0").json()
    assert [p["text"] for p in chapter["paragraphs"]] == BODY  # the reader can open it like any book
    again = client.post("/api/news/articles", json={"url": "https://www.example.com/news/wage"}).json()
    assert again["id"] == book["id"]  # same article, tracking parameters aside


def test_article_problems_come_back_as_readable_errors(env):
    client, _, monkeypatch = env

    def fail(url, client=None):
        raise NewsError("這一頁只有 12 個字，不像一篇文章")

    monkeypatch.setattr(news, "read_article", fail)
    res = client.post("/api/news/articles", json={"url": "https://a.com/video"})
    assert res.status_code == 400 and "不像一篇文章" in res.json()["detail"]
    assert client.post("/api/news/articles", json={"url": "nope"}).status_code == 400


def test_news_and_books_are_listed_separately(env, session):
    client, *_ = env
    session.add_all([Book(title="Novel", source="epub", source_key="a"), Book(title="Story", source="news", source_key="b"), Book(title="Alice", source="gutenberg", source_key="c")])
    session.commit()
    assert sorted(b["title"] for b in client.get("/api/books").json()) == ["Alice", "Novel"]
    assert [b["title"] for b in client.get("/api/books", params={"kind": "news"}).json()] == ["Story"]


def test_levels_for_many_words_at_once(env):
    from app.config import settings

    if not settings.dict_db_path.exists():
        pytest.skip("dict.sqlite not built")
    client, *_ = env
    levels = client.post("/api/dictionary/levels", json={"words": ["The", "house", "ubiquitous", "went", "zzzxqv", "123", "house"]}).json()["levels"]
    assert levels["the"] == 0 and levels["house"] == 0 and levels["ubiquitous"] >= 3 and levels["went"] == 0  # "went" counts as "go"
    assert "zzzxqv" not in levels and "123" not in levels and len(levels) == 4
    hyphen = client.post("/api/dictionary/levels", json={"words": ["four-year", "fair-minded", "well-known"]}).json()["levels"]
    assert set(hyphen) == {"four-year", "fair-minded", "well-known"} and hyphen["four-year"] <= 1  # not "rare" just for being a compound
    assert client.post("/api/dictionary/levels", json={"words": ["x"] * 4001}).status_code == 422


def test_an_old_database_gets_the_new_columns(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE book (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL)"))
        conn.execute(text("INSERT INTO book (id, title) VALUES (1, 'Old book')"))
        conn.execute(text("CREATE TABLE feed (id INTEGER PRIMARY KEY, url VARCHAR NOT NULL, title VARCHAR NOT NULL)"))
        conn.execute(text("INSERT INTO feed (id, url, title) VALUES (1, 'https://a.com/rss', 'Old feed')"))
        conn.execute(text("CREATE TABLE media (id INTEGER PRIMARY KEY, status VARCHAR)"))
        conn.execute(text("INSERT INTO media (id, status) VALUES (1, 'ready'), (2, 'transcribing')"))
    monkeypatch.setattr(db_module, "engine", engine)
    db_module._add_missing_columns()
    db_module._add_missing_columns()  # a second start changes nothing
    with engine.connect() as conn:
        assert {r[1] for r in conn.execute(text("PRAGMA table_info(book)"))} >= {"url", "published", "site"}
        assert conn.execute(text("SELECT url, site FROM book")).one() == ("", "")
        assert [r[0] for r in conn.execute(text("SELECT transcribed FROM media ORDER BY id"))] == [1, 0]
        assert conn.execute(text("SELECT kind, image FROM feed")).one() == ("news", "")  # feeds that existed are news feeds
