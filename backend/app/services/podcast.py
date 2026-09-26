"""Podcast sources: read an RSS feed's episodes, recognise a direct audio link, download an episode."""

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import httpx

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".flac", ".mp4")
MAX_FEED_BYTES = 8 * 1024 * 1024
MAX_AUDIO_BYTES = 600 * 1024 * 1024
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EnglishLab/1.0)"}


class PodcastError(ValueError):
    """Something about the link is wrong in a way the learner can act on; the message says what."""


@dataclass
class Episode:
    title: str
    audio_url: str
    published: str = ""
    duration: float = 0.0  # seconds, 0 if the feed does not say
    summary: str = ""


@dataclass
class Feed:
    title: str
    image: str
    episodes: list[Episode]

    def to_dict(self) -> dict:
        return {"title": self.title, "image": self.image, "episodes": [asdict(e) for e in self.episodes]}


def check_url(url: str) -> str:
    url = url.strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise PodcastError("請貼上以 http:// 或 https:// 開頭的完整網址")
    return url


def looks_like_audio_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(AUDIO_EXTENSIONS)


def parse_duration(value: str | int | float | None) -> float:
    """iTunes durations come as seconds, MM:SS or HH:MM:SS."""
    if value is None or value == "":
        return 0.0
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if 2 <= len(parts) <= 3 and all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + float(p)
        return seconds
    return 0.0


def _audio_link(entry) -> str:
    for link in entry.get("enclosures", []) or []:
        href = link.get("href") or link.get("url") or ""
        if href and ((link.get("type") or "").startswith("audio/") or looks_like_audio_url(href)):
            return href
    for link in entry.get("links", []) or []:
        href = link.get("href") or ""
        if href and ((link.get("type") or "").startswith("audio/") or link.get("rel") == "enclosure" and looks_like_audio_url(href)):
            return href
    return ""


def _plain(text: str, limit: int = 300) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def parse_feed(xml: str | bytes) -> Feed:
    parsed = feedparser.parse(xml)
    if not parsed.entries and not parsed.feed.get("title"):
        raise PodcastError("這不是有效的 Podcast RSS，也不是音檔連結")
    episodes = []
    for entry in parsed.entries:
        audio = _audio_link(entry)
        if not audio:
            continue  # an entry without audio (a blog post in the same feed) is not an episode
        published = ""
        if entry.get("published_parsed"):
            t = entry.published_parsed
            published = f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
        episodes.append(
            Episode(
                title=_plain(entry.get("title", ""), 200) or "（無標題）",
                audio_url=audio,
                published=published,
                duration=parse_duration(entry.get("itunes_duration")),
                summary=_plain(entry.get("summary", "")),
            )
        )
    if not episodes:
        raise PodcastError("這個 RSS 裡找不到任何有音檔的集數")
    image = ""
    img = parsed.feed.get("image") or {}
    image = img.get("href") or img.get("url") or ""
    return Feed(title=_plain(parsed.feed.get("title", ""), 200), image=image, episodes=episodes)


def fetch_feed_or_audio(url: str, client: httpx.Client | None = None) -> dict:
    """Look at what a link points to: {"type": "audio", ...} for an audio file, {"type": "feed", ...} for RSS."""
    url = check_url(url)
    if looks_like_audio_url(url):
        return {"type": "audio", "audio_url": url}
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=HEADERS)
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise PodcastError(f"無法讀取這個網址（HTTP {resp.status_code}）")
            if (resp.headers.get("content-type") or "").startswith("audio/"):
                return {"type": "audio", "audio_url": url}
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > MAX_FEED_BYTES:
                    raise PodcastError("這個網址的內容太大，不像是 Podcast RSS")
    except httpx.HTTPError as e:
        raise PodcastError(f"連不上這個網址：{e}") from e
    finally:
        if own:
            client.close()
    return {"type": "feed", **parse_feed(body).to_dict()}


def audio_filename(url: str, content_type: str = "") -> str:
    """A stable local file name for a download: hash of the link plus a sensible extension."""
    digest = hashlib.sha1(url.encode()).hexdigest()[:16]
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        ext = {"audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac", "audio/wav": ".wav",
               "audio/ogg": ".ogg", "audio/flac": ".flac"}.get(content_type.split(";")[0].strip().lower(), ".mp3")
    return f"podcast_{digest}{ext}"


def download_audio(url: str, dest_dir: Path, progress=None, client: httpx.Client | None = None) -> Path:
    """Download an episode. Returns the file (an earlier download of the same link is reused).
    `progress(fraction)` is called now and then when the size is known."""
    url = check_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    known = next(iter(dest_dir.glob(f"podcast_{hashlib.sha1(url.encode()).hexdigest()[:16]}.*")), None)
    if known and known.exists() and not known.name.endswith(".part"):
        return known
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True, headers=HEADERS)
    partial = None
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise PodcastError(f"下載失敗（HTTP {resp.status_code}）")
            target = dest_dir / audio_filename(url, resp.headers.get("content-type", ""))
            partial = target.with_suffix(target.suffix + ".part")
            total = int(resp.headers.get("content-length") or 0)
            if total > MAX_AUDIO_BYTES:
                raise PodcastError("音檔太大（超過 600 MB）")
            written, last_reported = 0, 0.0
            with partial.open("wb") as out:
                for chunk in resp.iter_bytes(1 << 16):
                    written += len(chunk)
                    if written > MAX_AUDIO_BYTES:
                        raise PodcastError("音檔太大（超過 600 MB）")
                    out.write(chunk)
                    if progress and total and written / total - last_reported >= 0.05:
                        last_reported = written / total
                        progress(last_reported)
            if written == 0:
                raise PodcastError("下載到的檔案是空的")
            partial.replace(target)
            partial = None
            return target
    except httpx.HTTPError as e:
        raise PodcastError(f"下載中斷：{e}") from e
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
        if own:
            client.close()
