import httpx
import pytest

from app.services import gutenberg
from app.services.gutenberg import GutenbergError

OPDS = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<id>http://www.gutenberg.org/ebooks/search.opds/?query=alice</id><title>Books: alice</title>
<entry><id>https://www.gutenberg.org/ebooks/subjects/search.opds/?query=alice</id><title>Subjects</title><content type="text">2 subject headings match.</content></entry>
<entry><id>https://www.gutenberg.org/ebooks/11.opds</id><title>Alice's Adventures in Wonderland</title><content type="text">Lewis Carroll</content></entry>
<entry><id>https://www.gutenberg.org/ebooks/23500.opds</id><title>The Car of Destiny</title><content type="text">C. N. Williamson</content></entry>
<entry><id>https://www.gutenberg.org/ebooks/authors/search.opds/?query=alice</id><title>Authors</title></entry>
</feed>"""


def opds_client(seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request.url)
        return httpx.Response(200, text=OPDS)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_lists_only_books_and_asks_for_english_most_downloaded_first():
    seen = []
    results = gutenberg.search("  alice   wonderland ", opds_client(seen))
    assert [r["id"] for r in results] == [11, 23500]
    assert results[0] == {"id": 11, "title": "Alice's Adventures in Wonderland", "author": "Lewis Carroll", "cover": "https://www.gutenberg.org/cache/epub/11/pg11.cover.medium.jpg"}
    assert seen[0].params["query"] == "alice wonderland l.en" and seen[0].params["sort_order"] == "downloads"


def test_empty_query_and_network_errors_give_readable_messages():
    with pytest.raises(GutenbergError, match="請輸入"):
        gutenberg.search("   ")

    def boom(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(GutenbergError, match="連不上"):
        gutenberg.search("alice", httpx.Client(transport=httpx.MockTransport(boom)))


def test_download_saves_the_epub_and_reports_missing_books(tmp_path):
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"PK-epub-bytes")))
    path = gutenberg.download_epub(11, tmp_path, ok)
    assert path.name == "gutenberg_11.epub" and path.read_bytes() == b"PK-epub-bytes"
    with pytest.raises(GutenbergError, match="找不到"):
        gutenberg.download_epub(999999, tmp_path, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    with pytest.raises(GutenbergError, match="HTTP 500"):
        gutenberg.download_epub(5, tmp_path, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert not list(tmp_path.glob("*.part")) and not (tmp_path / "gutenberg_5.epub").exists()


def test_a_download_that_breaks_off_leaves_no_partial_file(tmp_path):
    def cut(request):
        class Broken(httpx.SyncByteStream):
            def __iter__(self):
                yield b"partial"
                raise httpx.ReadError("connection lost")
        return httpx.Response(200, stream=Broken())

    with pytest.raises(GutenbergError, match="下載中斷"):
        gutenberg.download_epub(7, tmp_path, httpx.Client(transport=httpx.MockTransport(cut)))
    assert list(tmp_path.iterdir()) == []
