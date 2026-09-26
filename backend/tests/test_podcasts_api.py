from pathlib import Path

import pytest

from app.config import settings
from app.models import Media
from app.services import podcast
from app.services.podcast import PodcastError


@pytest.fixture
def env(client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    queued = []
    monkeypatch.setattr("app.routers.podcasts.pipeline.enqueue", queued.append)
    monkeypatch.setattr("app.routers.media.pipeline.enqueue", queued.append)
    return client, session, tmp_path, queued


def test_feed_endpoint_returns_what_the_link_is(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(podcast, "fetch_feed_or_audio", lambda url: {"type": "feed", "title": "Show", "image": "", "episodes": []})
    assert client.get("/api/podcasts/feed", params={"url": "https://a.com/rss"}).json()["type"] == "feed"


def test_feed_endpoint_turns_problems_into_400_with_the_reason(env, monkeypatch):
    client, *_ = env

    def fail(url):
        raise PodcastError("這不是有效的 Podcast RSS，也不是音檔連結")

    monkeypatch.setattr(podcast, "fetch_feed_or_audio", fail)
    res = client.get("/api/podcasts/feed", params={"url": "https://a.com/page"})
    assert res.status_code == 400 and "不是有效的 Podcast RSS" in res.json()["detail"]
    assert client.get("/api/podcasts/feed", params={"url": "not a url"}).status_code == 400


def test_adding_an_episode_creates_a_podcast_entry_and_queues_processing(env):
    client, session, _, queued = env
    body = {"audio_url": "https://media.example.com/6min/lazy_english.mp3?x=1", "title": "Is it OK to be lazy?", "thumbnail": "https://i.example.com/c.jpg", "duration": 372}
    row = client.post("/api/podcasts", json=body).json()
    assert row["kind"] == "podcast" and row["title"] == "Is it OK to be lazy?" and row["status"] == "pending" and row["playable"] is False
    assert row["thumbnail"] == "https://i.example.com/c.jpg" and queued == [row["id"]]
    assert session.get(Media, row["id"]).source_url == body["audio_url"]


def test_adding_the_same_episode_twice_does_not_duplicate_it(env):
    client, _, _, queued = env
    body = {"audio_url": "https://a.com/ep.mp3", "title": "Ep"}
    first, second = client.post("/api/podcasts", json=body).json(), client.post("/api/podcasts", json=body).json()
    assert first["id"] == second["id"] and queued == [first["id"]]
    assert len(client.get("/api/media", params={"kind": "podcast"}).json()) == 1


def test_a_missing_title_falls_back_to_the_file_name_and_bad_links_are_refused(env):
    client, *_ = env
    assert client.post("/api/podcasts", json={"audio_url": "https://a.com/x/my-nice_episode.mp3"}).json()["title"] == "my nice episode"
    assert client.post("/api/podcasts", json={"audio_url": "ftp://a.com/x.mp3"}).status_code == 400


def test_upload_saves_the_file_and_creates_an_entry_that_needs_no_download(env):
    client, session, tmp, queued = env
    res = client.post("/api/podcasts/upload", files={"file": ("My Talk.mp3", b"ID3" + b"x" * 5000, "audio/mpeg")}, data={"title": ""})
    row = res.json()
    assert res.status_code == 200 and row["kind"] == "podcast" and row["title"] == "My Talk" and queued == [row["id"]]
    stored = Path(session.get(Media, row["id"]).audio_path)
    assert stored.parent == tmp / "audio" and stored.exists() and stored.read_bytes().startswith(b"ID3")


def test_upload_refuses_non_audio_empty_and_oversized_files(env, monkeypatch):
    client, _, tmp, queued = env
    assert client.post("/api/podcasts/upload", files={"file": ("notes.txt", b"hello", "text/plain")}).status_code == 400
    assert client.post("/api/podcasts/upload", files={"file": ("a.mp3", b"", "audio/mpeg")}).status_code == 400
    monkeypatch.setattr("app.routers.podcasts.MAX_UPLOAD_BYTES", 100)
    assert client.post("/api/podcasts/upload", files={"file": ("a.mp3", b"x" * 500, "audio/mpeg")}).status_code == 413
    assert queued == [] and list((tmp / "audio").glob("*")) == []  # refused uploads leave no file behind


def test_media_list_can_be_filtered_by_kind(env, session):
    client, *_ = env
    session.add_all([Media(kind="video", source_url="v", title="V"), Media(kind="podcast", source_url="p", title="P")])
    session.commit()
    assert [m["title"] for m in client.get("/api/media", params={"kind": "video"}).json()] == ["V"]
    assert [m["title"] for m in client.get("/api/media", params={"kind": "podcast"}).json()] == ["P"]
    assert len(client.get("/api/media").json()) == 2


def test_audio_is_served_with_range_support_for_seeking(env, session):
    client, _, tmp, _ = env
    audio = tmp / "ep.mp3"
    audio.write_bytes(bytes(range(256)) * 40)
    m = Media(kind="podcast", source_url="p", title="P", audio_path=str(audio))
    session.add(m)
    session.commit()
    full = client.get(f"/api/media/{m.id}/audio")
    assert full.status_code == 200 and len(full.content) == 10240
    part = client.get(f"/api/media/{m.id}/audio", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == audio.read_bytes()[100:200]
    assert client.get("/api/media/9999/audio").status_code == 404


def test_deleting_an_entry_removes_its_audio_unless_another_entry_uses_the_same_file(env, session):
    client, _, tmp, _ = env
    audio = tmp / "shared.mp3"
    audio.write_bytes(b"x")
    a, b = Media(kind="podcast", source_url="a", title="A", audio_path=str(audio)), Media(kind="podcast", source_url="b", title="B", audio_path=str(audio))
    session.add_all([a, b])
    session.commit()
    client.delete(f"/api/media/{a.id}")
    assert audio.exists()  # B still needs it
    client.delete(f"/api/media/{b.id}")
    assert not audio.exists()


FEED = {"type": "feed", "title": "6 Minute English", "image": "https://i.example.com/6.jpg",
        "episodes": [{"title": "Ep 1", "audio_url": "https://a.com/1.mp3", "published": "", "duration": 360, "summary": ""}]}


def test_a_podcast_can_be_followed_listed_and_unfollowed(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(podcast, "fetch_feed_or_audio", lambda url: FEED)
    added = client.post("/api/podcasts/channels", json={"url": "https://a.com/rss"}).json()
    assert added["title"] == "6 Minute English" and added["image"] == "https://i.example.com/6.jpg"
    assert client.post("/api/podcasts/channels", json={"url": "https://a.com/rss"}).json()["id"] == added["id"]  # no duplicate
    assert [c["id"] for c in client.get("/api/podcasts/channels").json()] == [added["id"]]
    assert client.delete(f"/api/podcasts/channels/{added['id']}").json() == {"ok": True}
    assert client.get("/api/podcasts/channels").json() == []
    assert client.delete(f"/api/podcasts/channels/{added['id']}").status_code == 404


def test_only_a_podcast_feed_can_be_followed(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(podcast, "fetch_feed_or_audio", lambda url: {"type": "audio", "audio_url": url})
    res = client.post("/api/podcasts/channels", json={"url": "https://a.com/x.mp3"})
    assert res.status_code == 400 and "單一音檔" in res.json()["detail"]
    assert client.post("/api/podcasts/channels", json={"url": "nope"}).status_code == 400
    assert client.get("/api/podcasts/channels").json() == []


def test_a_channel_lists_its_current_episodes(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(podcast, "fetch_feed_or_audio", lambda url: FEED)
    channel = client.post("/api/podcasts/channels", json={"url": "https://a.com/rss"}).json()
    body = client.get(f"/api/podcasts/channels/{channel['id']}/episodes").json()
    assert body["episodes"][0]["title"] == "Ep 1" and body["title"] == "6 Minute English"

    def fail(url):
        raise PodcastError("連不上這個網址")

    monkeypatch.setattr(podcast, "fetch_feed_or_audio", fail)
    res = client.get(f"/api/podcasts/channels/{channel['id']}/episodes")
    assert res.status_code == 502 and "連不上" in res.json()["detail"]
    assert client.get("/api/podcasts/channels/999/episodes").status_code == 404


def test_podcast_channels_and_news_feeds_do_not_mix(env, monkeypatch):
    client, *_ = env
    monkeypatch.setattr(podcast, "fetch_feed_or_audio", lambda url: FEED)
    channel = client.post("/api/podcasts/channels", json={"url": "https://a.com/rss"}).json()
    assert client.get("/api/news/feeds").json() == []
    assert client.delete(f"/api/news/feeds/{channel['id']}").status_code == 404
    assert client.get(f"/api/news/feeds/{channel['id']}/items").status_code == 404
