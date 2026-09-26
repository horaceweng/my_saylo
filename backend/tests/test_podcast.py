import httpx
import pytest

from app.services import podcast
from app.services.podcast import PodcastError

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>6 Minute English</title>
    <itunes:image href="https://img.example.com/cover.jpg"/>
    <item>
      <title>Is it OK to be lazy?</title>
      <pubDate>Thu, 18 Sep 2026 05:00:00 GMT</pubDate>
      <itunes:duration>06:12</itunes:duration>
      <description>&lt;p&gt;Sam and Neil talk about &lt;b&gt;laziness&lt;/b&gt;.&lt;/p&gt;</description>
      <enclosure url="https://media.example.com/lazy.mp3" length="5000000" type="audio/mpeg"/>
    </item>
    <item>
      <title>A blog post without audio</title>
      <description>text only</description>
    </item>
    <item>
      <title>Long one</title>
      <itunes:duration>1:02:03</itunes:duration>
      <enclosure url="https://media.example.com/long.m4a?token=abc" type="audio/x-m4a"/>
    </item>
    <item>
      <title>Seconds only</title>
      <itunes:duration>754</itunes:duration>
      <enclosure url="https://media.example.com/plain.mp3" type=""/>
    </item>
  </channel>
</rss>"""


def test_feed_lists_only_episodes_that_have_audio():
    feed = podcast.parse_feed(RSS)
    assert feed.title == "6 Minute English" and feed.image == "https://img.example.com/cover.jpg"
    assert [e.title for e in feed.episodes] == ["Is it OK to be lazy?", "Long one", "Seconds only"]
    first = feed.episodes[0]
    assert first.audio_url == "https://media.example.com/lazy.mp3" and first.published == "2026-09-18"
    assert first.duration == 372 and first.summary == "Sam and Neil talk about laziness ."


def test_durations_in_every_itunes_style():
    assert podcast.parse_duration("06:12") == 372
    assert podcast.parse_duration("1:02:03") == 3723
    assert podcast.parse_duration("754") == 754
    assert podcast.parse_duration("") == 0 and podcast.parse_duration(None) == 0 and podcast.parse_duration("soon") == 0
    assert [e.duration for e in podcast.parse_feed(RSS).episodes] == [372, 3723, 754]


def test_a_feed_with_no_audio_or_a_web_page_is_rejected_with_a_clear_message():
    with pytest.raises(PodcastError, match="沒有音檔|找不到"):
        podcast.parse_feed("<rss version='2.0'><channel><title>Blog</title><item><title>Post</title></item></channel></rss>")
    with pytest.raises(PodcastError, match="不是有效的 Podcast RSS"):
        podcast.parse_feed("<html><body>hello</body></html>")


def test_only_http_links_are_accepted():
    for bad in ["", "not a url", "ftp://x.com/a.mp3", "file:///etc/passwd", "javascript:alert(1)"]:
        with pytest.raises(PodcastError):
            podcast.check_url(bad)
    assert podcast.check_url("  https://a.com/x  ") == "https://a.com/x"


def test_direct_audio_links_are_recognised_by_extension_or_content_type():
    assert podcast.looks_like_audio_url("https://a.com/ep.MP3?x=1") and not podcast.looks_like_audio_url("https://a.com/feed.xml")
    assert podcast.fetch_feed_or_audio("https://a.com/ep.mp3") == {"type": "audio", "audio_url": "https://a.com/ep.mp3"}

    def handler(request):
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"ID3....")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert podcast.fetch_feed_or_audio("https://a.com/listen/123", client)["type"] == "audio"


def test_fetching_a_feed_over_the_network():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "application/rss+xml"}, content=RSS.encode())))
    result = podcast.fetch_feed_or_audio("https://a.com/feed", client)
    assert result["type"] == "feed" and len(result["episodes"]) == 3


def test_network_problems_become_readable_errors():
    with pytest.raises(PodcastError, match="HTTP 404"):
        podcast.fetch_feed_or_audio("https://a.com/feed", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))

    def boom(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(PodcastError, match="連不上"):
        podcast.fetch_feed_or_audio("https://a.com/feed", httpx.Client(transport=httpx.MockTransport(boom)))


def test_download_saves_the_file_reports_progress_and_is_reused(tmp_path):
    data = b"x" * 300_000
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "audio/mpeg", "content-length": str(len(data))}, content=data)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    seen = []
    path = podcast.download_audio("https://a.com/ep.mp3", tmp_path, progress=seen.append, client=client)
    assert path.read_bytes() == data and path.name.startswith("podcast_") and path.suffix == ".mp3"
    assert seen and seen[-1] > 0.9 and all(0 < f <= 1 for f in seen)
    assert not list(tmp_path.glob("*.part"))
    again = podcast.download_audio("https://a.com/ep.mp3", tmp_path, client=client)
    assert again == path and len(calls) == 1  # not downloaded a second time


def test_download_picks_the_extension_from_the_content_type_when_the_link_has_none(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "audio/mp4"}, content=b"abc")))
    assert podcast.download_audio("https://a.com/download?id=7", tmp_path, client=client).suffix == ".m4a"


def test_failed_or_empty_downloads_leave_nothing_behind(tmp_path):
    with pytest.raises(PodcastError, match="HTTP 403"):
        podcast.download_audio("https://a.com/a.mp3", tmp_path, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))))
    with pytest.raises(PodcastError, match="空的"):
        podcast.download_audio("https://a.com/b.mp3", tmp_path, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b""))))

    def cut(request):
        class Broken(httpx.SyncByteStream):
            def __iter__(self):
                yield b"partial"
                raise httpx.ReadError("connection lost")
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, stream=Broken())

    with pytest.raises(PodcastError, match="下載中斷"):
        podcast.download_audio("https://a.com/c.mp3", tmp_path, client=httpx.Client(transport=httpx.MockTransport(cut)))
    assert list(tmp_path.iterdir()) == []


def test_files_too_large_are_refused_before_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(podcast, "MAX_AUDIO_BYTES", 1000)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-length": "5000"}, content=b"x" * 5000)))
    with pytest.raises(PodcastError, match="太大"):
        podcast.download_audio("https://a.com/big.mp3", tmp_path, client=client)
    assert list(tmp_path.iterdir()) == []
