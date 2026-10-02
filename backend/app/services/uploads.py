"""Files people send us: count the bytes while they arrive, then look at what is really inside.

Names given by the browser are never used as paths. A file that does not look like what its extension says is
refused, because audio goes on to ffmpeg, which would happily follow a text "playlist" to files or web addresses."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile

CHUNK = 1 << 20
MAX_EPUB_ENTRIES = 20000
MAX_EPUB_UNPACKED = 1024 * 1024 * 1024  # a zip bomb in disguise as a book


async def save_stream(file: UploadFile, dest: Path, limit: int, too_big: str, empty: str = "檔案是空的") -> tuple[int, str]:
    """Write the upload to `dest` chunk by chunk; stops with 413 as soon as it passes `limit` bytes.
    Returns (size, sha1). Whatever goes wrong, nothing is left at `dest`."""
    written, digest = 0, hashlib.sha1()
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(413, too_big)
                digest.update(chunk)
                out.write(chunk)
        if written == 0:
            raise HTTPException(400, empty)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return written, digest.hexdigest()


def audio_container(head: bytes) -> str | None:
    """Which audio/video container the first bytes announce (mp3, mp4/m4a, wav, ogg, flac, webm/mkv, aac), or None."""
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3/aac"  # an ID3 tag, or an MPEG/ADTS frame header
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"fLaC":
        return "flac"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def probe_audio(path: Path) -> float:
    """Ask ffprobe what the file holds. Returns its duration in seconds; raises ValueError if it has no audio."""
    try:
        run = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(run.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        raise ValueError("無法讀取這個音檔") from e
    if run.returncode != 0 or not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise ValueError("這個檔案裡沒有聲音")
    try:
        return float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        return 0.0


def check_audio_file(path: Path) -> float:
    """Raise HTTPException(400) unless `path` really is an audio file. Returns its duration (0 when unknown)."""
    with path.open("rb") as f:
        head = f.read(16)
    if audio_container(head) is None:
        raise HTTPException(400, "這不是音檔（檔案內容與副檔名不符）")
    try:
        return probe_audio(path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def check_epub(path: Path) -> None:
    """An EPUB is a zip whose first entry is `mimetype` saying application/epub+zip."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_EPUB_ENTRIES or sum(i.file_size for i in infos) > MAX_EPUB_UNPACKED:
                raise HTTPException(400, "這個 EPUB 的結構不正常")
            if "mimetype" not in z.namelist() or z.read("mimetype").strip() != b"application/epub+zip":
                raise HTTPException(400, "這不是有效的 EPUB 檔案")
    except zipfile.BadZipFile as e:
        raise HTTPException(400, "這不是有效的 EPUB 檔案") from e


def looks_like_text(head: bytes) -> bool:
    """Plain text has no NUL bytes; anything else (a zip, an image, a PDF renamed to .txt) is not a book."""
    return b"\x00" not in head
