import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.db import engine, get_session
from app.deps import admin_user, current_user
from app.models import Book, Feed, Setting, User
from app.routers.books import book_out, progress_of, store_book
from app.services import books, news
from app.services.books import BookError, ParsedBook, ParsedChapter
from app.services.news import NewsError

router = APIRouter(prefix="/api/news", tags=["news"])


class FeedIn(BaseModel):
    url: str


class ArticleIn(BaseModel):
    url: str


def ensure_default_feeds() -> None:
    """Give a new installation a ladder of feeds from easy to hard. Done once: feeds the learner deletes stay deleted."""
    with Session(engine) as session:
        if session.get(Setting, "default_feeds_added"):
            return
        if not session.exec(select(func.count()).select_from(Feed).where(Feed.kind == "news")).one():
            session.add_all(Feed(title=title, url=url) for title, url in news.DEFAULT_FEEDS)
        session.add(Setting(key="default_feeds_added", value="1"))
        session.commit()


def _feed_out(feed: Feed) -> dict:
    return {"id": feed.id, "title": feed.title, "url": feed.url}


@router.get("/feeds")
def list_feeds(session: Session = Depends(get_session)):
    return [_feed_out(f) for f in session.exec(select(Feed).where(Feed.kind == "news").order_by(Feed.id)).all()]


@router.post("/feeds")
async def add_feed(body: FeedIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Follow a feed. It is opened once first, so a link that is not a feed is refused with a reason."""
    try:
        url = news.check_url(body.url)
        existing = session.exec(select(Feed).where(Feed.kind == "news", Feed.url == url)).first()
        if existing:
            return _feed_out(existing)
        title, _ = await asyncio.to_thread(news.read_feed, url)
    except NewsError as e:
        raise HTTPException(400, str(e)) from e
    feed = Feed(url=url, title=title, added_by=user.id)
    session.add(feed)
    session.commit()
    session.refresh(feed)
    return _feed_out(feed)


@router.delete("/feeds/{feed_id}")
def delete_feed(feed_id: int, session: Session = Depends(get_session), _: User = Depends(admin_user)):
    feed = session.get(Feed, feed_id)
    if not feed or feed.kind != "news":
        raise HTTPException(404, "找不到這個訂閱")
    session.delete(feed)
    session.commit()
    return {"ok": True}


@router.get("/feeds/{feed_id}/items")
async def feed_items(feed_id: int, limit: int = 30, session: Session = Depends(get_session)):
    """The latest articles of a feed. Those the learner has already opened carry their id and level."""
    feed = session.get(Feed, feed_id)
    if not feed or feed.kind != "news":
        raise HTTPException(404, "找不到這個訂閱")
    try:
        _, items = await asyncio.to_thread(news.read_feed, feed.url)
    except NewsError as e:
        raise HTTPException(502, str(e)) from e
    items = items[: max(1, min(limit, 60))]
    keys = {news.url_key(i.url): i for i in items}
    saved = {b.source_key: b for b in session.exec(select(Book).where(col(Book.source_key).in_(list(keys))))}
    return [
        {
            "title": i.title, "url": i.url, "published": i.published, "summary": i.summary,
            "article_id": saved[k].id if k in saved else None, "level": saved[k].level if k in saved else "",
        }
        for k, i in keys.items()
    ]


@router.post("/articles")
async def add_article(body: ArticleIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Fetch a page, keep the article text, estimate its level and store it ready to read."""
    try:
        url = news.check_url(body.url)
    except NewsError as e:
        raise HTTPException(400, str(e)) from e
    key = news.url_key(url)
    if found := session.exec(select(Book).where(Book.source_key == key)).first():
        return book_out(found, progress_of(session, user.id, found.id))
    bind, user_id = session.get_bind(), user.id

    def work() -> Book:
        article = news.read_article(url)
        parsed = books.finalize(ParsedBook(article.title, article.author, [ParsedChapter(article.title, article.paragraphs)]))
        with Session(bind) as s:
            return store_book(s, parsed, "news", key, cover=article.image, url=article.url, published=article.published, site=article.site, added_by=user_id)

    try:
        return book_out(await asyncio.to_thread(work))
    except (NewsError, BookError) as e:
        raise HTTPException(400, str(e)) from e
