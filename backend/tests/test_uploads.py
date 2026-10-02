import io
import shutil
import wave
import zipfile

import pytest

from app.config import settings
from app.models import Media, Segment
from app.services import uploads
from tests.test_books import make_epub, para


def wav_bytes(seconds=1.0, rate=8000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def env(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("app.routers.podcasts.pipeline.enqueue", lambda media_id: None)
    return client, tmp_path


def leftovers(tmp_path):
    return [p for p in tmp_path.rglob("*") if p.is_file()]


def test_the_container_is_recognised_from_the_first_bytes():
    assert uploads.audio_container(b"ID3\x04" + b"\0" * 12) == "mp3/aac"
    assert uploads.audio_container(b"\xff\xfb\x90\x00" + b"\0" * 12)
    assert uploads.audio_container(wav_bytes()[:16]) == "wav"
    assert uploads.audio_container(b"\0\0\0\x20ftypM4A " + b"\0" * 4) == "mp4"
    assert uploads.audio_container(b"\x1a\x45\xdf\xa3" + b"\0" * 12) == "webm"
    for junk in (b"#EXTM3U\n#EXTINF:1,\nfile:///etc/passwd\n", b"ffconcat version 1.0\nfile '/etc/passwd'\n", b"<html>", b"%PDF-1.7", b"PK\x03\x04", b""):
        assert uploads.audio_container(junk.ljust(16, b" ")) is None


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_ffprobe_tells_real_audio_from_a_file_that_only_starts_like_audio(tmp_path, monkeypatch):
    monkeypatch.undo()  # the suite replaces probe_audio; here the real one is wanted
    real = tmp_path / "a.wav"
    real.write_bytes(wav_bytes(2.0))
    assert 1.9 < uploads.probe_audio(real) < 2.1
    fake = tmp_path / "b.mp3"
    fake.write_bytes(b"ID3" + b"\0" * 200)
    with pytest.raises(ValueError):
        uploads.probe_audio(fake)


def test_a_podcast_upload_must_be_audio_inside_not_only_by_name(env):
    client, tmp = env
    for name, data in (("a.mp3", b"#EXTM3U\nfile:///etc/passwd\n"), ("b.m4a", b"%PDF-1.7 " + b"x" * 100), ("c.wav", b"RIFF")):
        res = client.post("/api/podcasts/upload", files={"file": (name, data)})
        assert res.status_code == 400, name
    assert leftovers(tmp) == []
    assert client.post("/api/podcasts/upload", files={"file": ("ok.wav", wav_bytes())}).status_code == 200


def test_the_name_the_browser_gives_is_never_part_of_a_path(env):
    client, tmp = env
    res = client.post("/api/podcasts/upload", files={"file": ("../../../etc/evil.mp3", b"ID3" + b"x" * 100)})
    assert res.status_code == 200
    files = leftovers(tmp)
    assert len(files) == 1 and files[0].parent == tmp / "audio" and files[0].name.startswith("upload_")


def test_an_upload_is_cut_off_at_the_limit_without_reading_it_all(env, monkeypatch):
    client, tmp = env
    monkeypatch.setattr(uploads, "CHUNK", 1000)
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    user = client  # admin: the endpoint's own ceiling applies; shrink it for the test
    monkeypatch.setattr("app.routers.podcasts.MAX_UPLOAD_BYTES", 5000)
    res = user.post("/api/podcasts/upload", files={"file": ("a.mp3", b"ID3" + b"x" * 20000)})
    assert res.status_code == 413
    monkeypatch.setattr("app.routers.books.MAX_UPLOAD_BYTES", 5000)
    assert client.post("/api/books/upload", files={"file": ("a.txt", b"word " * 5000)}).status_code == 413
    assert leftovers(tmp) == []


def test_the_book_upload_limit_for_users_is_the_same_configured_limit(make_client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    alice = make_client("alice")
    res = alice.post("/api/books/upload", files={"file": ("a.txt", b"word " * 300_000)})
    assert res.status_code == 413 and "1 MB" in res.json()["detail"]
    assert leftovers(tmp_path) == []


def test_epub_must_be_a_zip_with_the_epub_mimetype(env, tmp_path):
    client, tmp = env
    src = tmp_path / "src"
    src.mkdir()
    good = make_epub(src, [("c1.xhtml", f"<h2>One</h2><p>{para()}</p><p>{para()}</p>")], title="T", author="A").read_bytes()
    assert client.post("/api/books/upload", files={"file": ("x.epub", good)}).status_code == 200
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as z:
        z.writestr("hello.txt", "hi")
    other = io.BytesIO()
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("mimetype", "application/zip")
    for data in (plain_zip.getvalue(), other.getvalue(), b"not a zip at all", b"%PDF-1.4"):
        assert client.post("/api/books/upload", files={"file": ("y.epub", data)}).status_code == 400
    assert [p for p in tmp.iterdir() if p.name.startswith("upload_")] == []  # temp files are gone


def test_a_text_upload_with_binary_content_is_refused(env):
    client, _ = env
    assert client.post("/api/books/upload", files={"file": ("a.txt", b"PK\x03\x04\x00\x00" + b"\0" * 100)}).status_code == 400


def test_recording_must_be_audio_and_leaves_nothing_behind(env, session):
    client, tmp = env
    media = Media(source_url="u", external_id="abcdefghijk", title="T", status="ready")
    session.add(media)
    session.commit()
    seg = Segment(media_id=media.id, idx=0, start=0, end=1, text="Hello there")
    session.add(seg)
    session.commit()
    res = client.post(f"/api/segments/{seg.id}/recordings", files={"file": ("../../x.webm", b"#EXTM3U\nfile:///etc/passwd\n")})
    assert res.status_code == 400
    assert leftovers(tmp) == []
