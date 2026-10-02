"""Project Gutenberg: search the catalogue and download a book as EPUB (official OPDS feed, no key needed)."""

import re
from pathlib import Path
from urllib.parse import urlencode

import feedparser
import httpx

from app.services import safe_fetch

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EnglishLab/1.0)"}
TIMEOUT = httpx.Timeout(45.0, connect=10.0)
MAX_EPUB_BYTES = 60 * 1024 * 1024
MAX_FEED_BYTES = 4 * 1024 * 1024
_BOOK_ENTRY = re.compile(r"/ebooks/(\d+)\.opds$")


class GutenbergError(ValueError):
    """Search or download did not work; the message says what the learner can do."""


def cover_url(book_id: int) -> str:
    return f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.cover.medium.jpg"


def search(query: str, client: httpx.Client | None = None) -> list[dict]:
    """English books matching `query`, the most downloaded first: [{id, title, author, cover}]."""
    query = " ".join(query.split())
    if not query:
        raise GutenbergError("請輸入書名或作者")
    url = "https://www.gutenberg.org/ebooks/search.opds/?" + urlencode({"query": f"{query} l.en", "sort_order": "downloads"})
    try:
        resp = safe_fetch.fetch(url, max_bytes=MAX_FEED_BYTES, timeout=TIMEOUT, headers=HEADERS, client=client)
        if resp.status_code >= 400:
            raise GutenbergError(f"連不上 Project Gutenberg，請稍後再試（HTTP {resp.status_code}）")
    except (httpx.HTTPError, safe_fetch.FetchError) as e:
        raise GutenbergError(f"連不上 Project Gutenberg，請稍後再試（{e}）") from e
    results = []
    for entry in feedparser.parse(resp.content).entries:
        match = _BOOK_ENTRY.search(entry.get("id", ""))
        if not match:
            continue  # "Subjects", "Authors" and paging entries share the feed
        book_id = int(match.group(1))
        author = (entry.get("content") or [{}])[0].get("value") or entry.get("summary", "")
        results.append({"id": book_id, "title": entry.get("title", "").strip(), "author": author.strip(), "cover": cover_url(book_id)})
    return results


def download_epub(book_id: int, dest_dir: Path, client: httpx.Client | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"gutenberg_{book_id}.epub"
    partial = target.with_suffix(".part")
    try:
        with safe_fetch.open_stream(f"https://www.gutenberg.org/ebooks/{book_id}.epub.noimages", timeout=httpx.Timeout(120.0, connect=10.0), headers=HEADERS, client=client) as resp:
            if resp.status_code == 404:
                raise GutenbergError("Project Gutenberg 找不到這本書的 EPUB")
            if resp.status_code >= 400:
                raise GutenbergError(f"下載失敗（HTTP {resp.status_code}）")
            written = 0
            with partial.open("wb") as out:
                for chunk in resp.iter_bytes(1 << 16):
                    written += len(chunk)
                    if written > MAX_EPUB_BYTES:
                        raise GutenbergError("這個檔案太大")
                    out.write(chunk)
        if written == 0:
            raise GutenbergError("下載到的檔案是空的")
        partial.replace(target)
        return target
    except safe_fetch.FetchError as e:
        raise GutenbergError(str(e)) from e
    except httpx.HTTPError as e:
        raise GutenbergError(f"下載中斷：{e}") from e
    finally:
        partial.unlink(missing_ok=True)
