"""Project Gutenberg: search the catalogue and download a book as EPUB (official OPDS feed, no key needed)."""

import re
from pathlib import Path

import feedparser
import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EnglishLab/1.0)"}
TIMEOUT = httpx.Timeout(45.0, connect=10.0)
MAX_EPUB_BYTES = 60 * 1024 * 1024
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
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS)
    try:
        resp = client.get("https://www.gutenberg.org/ebooks/search.opds/", params={"query": f"{query} l.en", "sort_order": "downloads"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise GutenbergError(f"連不上 Project Gutenberg，請稍後再試（{e}）") from e
    finally:
        if own:
            client.close()
    results = []
    for entry in feedparser.parse(resp.text).entries:
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
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=True, headers=HEADERS)
    try:
        with client.stream("GET", f"https://www.gutenberg.org/ebooks/{book_id}.epub.noimages") as resp:
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
    except httpx.HTTPError as e:
        raise GutenbergError(f"下載中斷：{e}") from e
    finally:
        partial.unlink(missing_ok=True)
        if own:
            client.close()
