"""Learning records belong to one user; shared content (videos, books, feeds) is shared, deleting it is for admins."""

import io
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest
from sqlmodel import select

from app.config import settings
from app.models import Book, Feed, Media, Recording, SavedPhrase, Segment
from app.services import auth, shadowing
from app.services.segmenter import Word

PHRASE = {"text": "break the ice", "translation": "打破僵局"}


def test_phrases_are_private(user_client, other_client):
    mine = user_client.post("/api/phrases", json=PHRASE).json()
    assert [p["id"] for p in user_client.get("/api/phrases").json()] == [mine["id"]]
    assert other_client.get("/api/phrases").json() == []
    assert other_client.get("/api/phrases?q=ice").json() == []
    review = other_client.get("/api/phrases/review").json()
    assert review["cards"] == [] and review["total"] == 0 and review["due_count"] == 0
    assert other_client.post(f"/api/phrases/{mine['id']}/review", json={"grade": 2}).status_code == 404
    assert other_client.delete(f"/api/phrases/{mine['id']}").status_code == 404
    assert user_client.get("/api/phrases/review").json()["total"] == 1  # still there, untouched


def test_two_users_can_save_the_same_phrase(user_client, other_client):
    a = user_client.post("/api/phrases", json=PHRASE).json()
    b = other_client.post("/api/phrases", json=PHRASE).json()
    assert a["id"] != b["id"]


def test_ownerless_phrases_are_invisible_until_an_admin_claims_them(client, session):
    session.add(SavedPhrase(text="old one"))
    session.commit()
    assert client.get("/api/phrases").json() == []
    admin_id = client.get("/api/auth/me").json()["id"]
    assert auth.claim_ownerless_rows(session, admin_id) == 1
    assert [p["text"] for p in client.get("/api/phrases").json()] == ["old one"]


def wav_bytes(seconds=2.0) -> bytes:
    t = np.arange(int(seconds * 16000)) / 16000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_recordings_are_private_and_stored_per_user(user_client, other_client, session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(shadowing, "transcribe_recording", lambda wav: [Word("Hello", 0, 0.3, 0.9), Word("world", 0.4, 0.7, 0.9)])
    media = Media(source_url="u", title="T", status="ready")
    session.add(media)
    session.commit()
    seg = Segment(media_id=media.id, idx=0, start=0, end=1, text="Hello world")
    session.add(seg)
    session.commit()

    rec = user_client.post(f"/api/segments/{seg.id}/recordings", files={"file": ("a.wav", wav_bytes(), "audio/wav")}).json()
    row = session.get(Recording, rec["id"])
    owner = user_client.get("/api/auth/me").json()["id"]
    assert row.user_id == owner and Path(row.file_path).parent == tmp_path / "recordings" / str(owner)

    assert user_client.get(f"/api/recordings/{rec['id']}/audio").status_code == 200
    assert other_client.get(f"/api/segments/{seg.id}/recordings").json() == []
    assert other_client.get(f"/api/recordings/{rec['id']}/audio").status_code == 404
    assert other_client.post(f"/api/recordings/{rec['id']}/feedback/stream").status_code == 404
    assert other_client.delete(f"/api/recordings/{rec['id']}").status_code == 404
    assert Path(row.file_path).exists()
    assert user_client.delete(f"/api/recordings/{rec['id']}").status_code == 200


def test_shared_content_is_visible_to_everyone_but_only_admins_delete_it(client, user_client, session):
    media = Media(source_url="u", external_id="abcdefghijk", title="Shared video", status="ready")
    book = Book(title="Shared book")
    feed = Feed(url="http://example.com/feed", title="Feed")
    podcast = Feed(kind="podcast", url="http://example.com/pod", title="Pod")
    session.add_all([media, book, feed, podcast])
    session.commit()
    assert [m["title"] for m in user_client.get("/api/media").json()] == ["Shared video"]
    assert user_client.get("/api/books").status_code == 200
    for url in (f"/api/media/{media.id}", f"/api/books/{book.id}", f"/api/news/feeds/{feed.id}", f"/api/podcasts/channels/{podcast.id}"):
        assert user_client.delete(url).status_code == 403, url
    assert session.get(Media, media.id) and session.get(Book, book.id) and session.get(Feed, feed.id)
    for url in (f"/api/media/{media.id}", f"/api/books/{book.id}", f"/api/news/feeds/{feed.id}", f"/api/podcasts/channels/{podcast.id}"):
        assert client.delete(url).status_code == 200, url


def test_imported_content_records_who_added_it(user_client, session):
    res = user_client.post("/api/books/upload", files={"file": ("s.txt", (("The little fox walked slowly through the quiet forest. " * 12 + "\n\n") * 6).encode(), "text/plain")})
    assert res.status_code == 200
    book = session.exec(select(Book)).one()
    assert book.added_by == user_client.get("/api/auth/me").json()["id"]
