import ipaddress
import urllib.request

import httpx
import pytest

from app.services import news, podcast, safe_fetch
from app.services.safe_fetch import FetchError

TIMEOUT = httpx.Timeout(5.0)


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434", "http://127.0.0.1/", "http://localhost/x", "http://LOCALHOST./x", "http://192.168.50.1/", "http://10.0.0.5/",
        "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/", "http://100.64.0.1/", "http://100.101.102.103/", "http://0.0.0.0/",
        "http://224.0.0.1/", "http://240.0.0.1/", "http://[::1]/", "http://[::]/", "http://[fe80::1]/", "http://[fc00::1]/", "http://[fd7a:115c:a1e0::1]/",
        "http://[::ffff:127.0.0.1]/", "http://[::ffff:192.168.1.1]/", "http://[2002:7f00:1::]/", "http://[64:ff9b::7f00:1]/", "http://2130706433/",
        "http://0x7f.0.0.1/", "http://horacemac-mini.tailcf37df.ts.net:4321", "http://horacemac-mini.tailcf37df.ts.net/", "http://printer.local/",
        "http://db.internal/", "http://intranet/", "http://example.com:8080/", "http://example.com:11434/", "http://example.com:22/",
        "ftp://example.com/", "file:///etc/passwd", "gopher://example.com/", "javascript:alert(1)", "http://user:pw@example.com/", "http:///x", "",
    ],
)
def test_addresses_on_this_machine_or_its_networks_are_refused(url):
    with pytest.raises(FetchError):
        safe_fetch.vet(url)


def test_names_are_resolved_here_and_one_bad_answer_is_enough_to_refuse(monkeypatch):
    monkeypatch.setattr(safe_fetch, "resolve", lambda host, port: ["93.184.216.34", "10.1.2.3"])
    with pytest.raises(FetchError):
        safe_fetch.vet("https://example.com/feed")
    monkeypatch.setattr(safe_fetch, "resolve", lambda host, port: ["::ffff:10.1.2.3"])
    with pytest.raises(FetchError):
        safe_fetch.vet("https://example.com/feed")
    monkeypatch.setattr(safe_fetch, "resolve", lambda host, port: ["93.184.216.34", "2606:2800:220:1::1"])
    url, host, port, addresses = safe_fetch.vet("https://Example.com./feed")
    assert (host, port, addresses) == ("example.com", 443, ["93.184.216.34", "2606:2800:220:1::1"])


@pytest.mark.parametrize("url", ["http://93.184.216.34/", "https://example.com/a?b=1", "http://example.com:80/", "https://[2606:2800:220:1::1]/"])
def test_ordinary_public_links_pass(url):
    safe_fetch.vet(url)


def test_the_connection_goes_to_the_vetted_address_with_the_real_name(monkeypatch):
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(200, content=b"hello")

    monkeypatch.setattr(safe_fetch, "new_client", lambda timeout, headers=None: client_for(handler))
    resolved = []
    monkeypatch.setattr(safe_fetch, "resolve", lambda host, port: resolved.append(host) or ["93.184.216.34"])
    res = safe_fetch.fetch("https://example.com/a?x=1", max_bytes=100)
    assert res.content == b"hello"
    assert seen == [("https://93.184.216.34/a?x=1", "example.com", "example.com")]
    assert resolved == ["example.com"]  # resolved once: nothing can change its answer between the check and the connection


def test_a_redirect_to_the_machine_itself_is_refused_before_it_is_followed():
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1:11434/api/tags"})

    with pytest.raises(FetchError, match="內部網路"):
        safe_fetch.fetch("https://example.com/start", max_bytes=100, client=client_for(handler))
    assert requests == ["https://example.com/start"]


def test_every_hop_is_checked_with_its_own_name(monkeypatch):
    answers = {"a.example.com": ["93.184.216.34"], "b.example.com": ["192.168.1.1"]}
    monkeypatch.setattr(safe_fetch, "resolve", lambda host, port: answers[host])
    hops = []

    def handler(request):
        hops.append(request.url.host)
        return httpx.Response(301, headers={"location": "http://b.example.com/x"}) if request.url.host == "a.example.com" else httpx.Response(200)

    with pytest.raises(FetchError):
        safe_fetch.fetch("http://a.example.com/", max_bytes=100, client=client_for(handler))
    assert hops == ["a.example.com"]


def test_relative_redirects_work_and_a_loop_ends():
    def ok(request):
        return httpx.Response(302, headers={"location": "/final"}) if request.url.path == "/start" else httpx.Response(200, content=request.url.path.encode())

    assert safe_fetch.fetch("https://example.com/start", max_bytes=100, client=client_for(ok)).content == b"/final"
    with pytest.raises(FetchError, match="轉址太多"):
        safe_fetch.fetch("https://example.com/", max_bytes=100, client=client_for(lambda r: httpx.Response(302, headers={"location": "/"})))


def test_a_body_larger_than_the_limit_is_cut_off_while_it_streams():
    with pytest.raises(FetchError, match="太大"):
        safe_fetch.fetch("https://example.com/", max_bytes=1000, client=client_for(lambda r: httpx.Response(200, content=b"x" * 5000)))
    with pytest.raises(FetchError, match="太大"):  # declared up front
        safe_fetch.fetch("https://example.com/", max_bytes=1000, client=client_for(lambda r: httpx.Response(200, headers={"content-length": "999999"}, content=b"x")))


def test_the_services_turn_a_refusal_into_their_own_readable_error():
    with pytest.raises(news.NewsError, match="內部網路"):
        news.fetch_html("http://127.0.0.1:11434/")
    with pytest.raises(news.NewsError):
        news.read_feed("http://192.168.50.1/rss")
    with pytest.raises(podcast.PodcastError, match="內部網路"):
        podcast.fetch_feed_or_audio("http://horacemac-mini.tailcf37df.ts.net:4321/feed")


def test_feedparser_never_opens_a_link_or_file_by_itself(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("feedparser tried to fetch")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", boom)
    for text in ("http://127.0.0.1:11434/feed", str(tmp_path)):
        with pytest.raises(podcast.PodcastError):
            podcast.parse_feed(text)


def test_the_api_refuses_internal_addresses(client):
    for path, body in (("/api/news/articles", {"url": "http://127.0.0.1:11434"}), ("/api/news/feeds", {"url": "http://192.168.50.1/rss"}),
                       ("/api/podcasts/channels", {"url": "http://100.100.1.1/feed"}), ("/api/podcasts", {"audio_url": "http://10.0.0.1/a.mp3"})):
        res = client.post(path, json=body)
        assert res.status_code == 400 and "內部網路" in res.json()["detail"], path
    assert client.get("/api/podcasts/feed", params={"url": "http://localhost:8000/x.mp3"}).status_code == 400
    assert ipaddress.ip_address("100.64.0.1").is_global is False  # the Python behind the check knows Tailscale's range is not public
