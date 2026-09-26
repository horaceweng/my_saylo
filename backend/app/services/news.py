"""News articles: fetch a page, pull out the article text, read RSS feeds."""

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx
import trafilatura

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EnglishLab/1.0)", "Accept-Language": "en"}
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_PAGE_BYTES = 6 * 1024 * 1024
MIN_ARTICLE_WORDS = 80
_TRACKING = re.compile(r"^(utm_|at_|ocid$|cmp$|xtor$|ns_|fbclid$|gclid$|mc_|ref$|smid$|taid$|embedded-checkout$)", re.I)

# One-line leftovers of page furniture that the extractor keeps: "- Published", photo credits, share buttons.
_NOISE_LINE = re.compile(
    r"^(?:-\s*)?(?:published|updated|share|save|advertisement|sign up|subscribe|related topics?|read more|listen|watch)\b.{0,30}$"
    r"|^(?:getty images|reuters|afp|ap|epa|pa media|bbc|image source|image caption|photo|photograph)[:\s\w/.,-]{0,40}$",
    re.I,
)
DEFAULT_FEEDS = [
    ("VOA Learning English · Health & Lifestyle", "https://learningenglish.voanews.com/api/zmmpql-vomx-tpey-_q"),
    ("VOA Learning English · As It Is", "https://learningenglish.voanews.com/api/zkm-ql-vomx-tpej-rqi"),
    ("VOA Learning English · Science & Technology", "https://learningenglish.voanews.com/api/zmg_pl-vomx-tpeymtm"),
    ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
    ("The Guardian · World", "https://www.theguardian.com/world/rss"),
]


class NewsError(ValueError):
    """The page or feed could not be used; the message says why."""


@dataclass
class Article:
    title: str
    author: str
    published: str
    site: str
    image: str
    url: str
    paragraphs: list[str] = field(default_factory=list)


@dataclass
class FeedItem:
    title: str
    url: str
    published: str = ""
    summary: str = ""


def check_url(url: str) -> str:
    url = url.strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise NewsError("請貼上以 http:// 或 https:// 開頭的完整網址")
    return url


def canonical_url(url: str) -> str:
    """The link without tracking parameters and fragment, so one article is one article."""
    parts = urlparse(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    return urlunparse((parts.scheme, parts.netloc.lower(), parts.path, "", query, ""))


def url_key(url: str) -> str:
    return "url:" + hashlib.sha1(canonical_url(url).encode()).hexdigest()


def fetch_html(url: str, client: httpx.Client | None = None) -> str:
    url = check_url(url)
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS)
    try:
        resp = client.get(url)
        if resp.status_code in (401, 402, 403):
            raise NewsError(f"這個網站不讓程式讀取（HTTP {resp.status_code}），可能需要登入或有付費牆")
        if resp.status_code >= 400:
            raise NewsError(f"無法讀取這個網址（HTTP {resp.status_code}）")
        if len(resp.content) > MAX_PAGE_BYTES:
            raise NewsError("這個網頁太大，不像是一篇文章")
        return resp.text
    except httpx.HTTPError as e:
        raise NewsError(f"連不上這個網址：{e}") from e
    finally:
        if own:
            client.close()


def looks_english(text: str) -> bool:
    words = re.findall(r"[A-Za-z']+", text.lower())
    letters = sum(c.isalpha() for c in text) or 1
    ascii_share = sum(c.isascii() and c.isalpha() for c in text) / letters
    common = sum(w in {"the", "and", "of", "to", "in", "a", "is", "that", "for", "it", "was", "on", "with"} for w in words)
    return ascii_share > 0.9 and len(words) > 0 and common / len(words) > 0.08


def clean_paragraphs(text: str, title: str) -> list[str]:
    paragraphs: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"(?<=\w)\s*,\s*external(?=[a-z\s,]|$)", " ", line)  # BBC's hidden "external link" label after a link
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)  # "word ," left over from a link's markup
        line = re.sub(r"\s+", " ", line).strip()
        if not line or _NOISE_LINE.match(line) or re.fullmatch(r"[\s_\-–—=*~.·•]{3,}", line):
            continue  # empty, page furniture, or a divider line
        if line.lower() == title.lower() and not paragraphs:
            continue  # the headline repeated as the first line
        if paragraphs and line == paragraphs[-1]:
            continue
        paragraphs.append(line)
    return paragraphs


def extract_article(html: str, url: str) -> Article:
    doc = trafilatura.bare_extraction(
        html, url=url, include_comments=False, include_tables=False, favor_precision=True, with_metadata=True
    )
    if doc is None or not (doc.text or "").strip():
        raise NewsError("抓不到這一頁的文章內容（可能是影片或音檔頁面，或需要登入、靠 JavaScript 才會顯示內容）")
    title = re.sub(r"\s+", " ", doc.title or "").strip()
    paragraphs = clean_paragraphs(doc.text, title)
    words = sum(len(p.split()) for p in paragraphs)
    if words < MIN_ARTICLE_WORDS:
        raise NewsError(f"這一頁只有 {words} 個字，不像一篇文章（可能是影片、音檔頁面，或有付費牆）")
    if not looks_english(" ".join(paragraphs)):
        raise NewsError("這篇文章不是英文")
    site = (doc.sitename or "").strip() or urlparse(url).netloc.removeprefix("www.")
    return Article(
        title=title or paragraphs[0][:120], author=(doc.author or "").strip()[:200], published=(doc.date or "")[:10],
        site=site[:100], image=doc.image or "", url=canonical_url(url), paragraphs=paragraphs,
    )


def read_article(url: str, client: httpx.Client | None = None) -> Article:
    url = check_url(url)
    return extract_article(fetch_html(url, client), url)


def _plain(text: str, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()[:limit]


def read_feed(url: str, client: httpx.Client | None = None) -> tuple[str, list[FeedItem]]:
    """(feed title, latest items). Raises NewsError if the link is not a feed with articles."""
    url = check_url(url)
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS)
    try:
        resp = client.get(url)
        if resp.status_code >= 400:
            raise NewsError(f"無法讀取這個訂閱（HTTP {resp.status_code}）")
    except httpx.HTTPError as e:
        raise NewsError(f"連不上這個網址：{e}") from e
    finally:
        if own:
            client.close()
    parsed = feedparser.parse(resp.content)
    items = []
    for entry in parsed.entries:
        link = entry.get("link", "")
        if not link:
            continue
        published = ""
        if entry.get("published_parsed"):
            t = entry.published_parsed
            published = f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
        items.append(FeedItem(title=_plain(entry.get("title", ""), 200) or "（無標題）", url=link, published=published, summary=_plain(entry.get("summary", ""))))
    if not items:
        raise NewsError("這不是有效的 RSS／Atom 訂閱，或裡面沒有文章")
    return _plain(parsed.feed.get("title", ""), 100) or urlparse(url).netloc, items
