import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp

from app.config import settings

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    """Return the 11-char video id from any common YouTube URL form."""
    url = url.strip()
    if _ID_RE.match(url):
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.").removeprefix("m.")
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = [p for p in parsed.path.split("/") if p]
            candidate = parts[1] if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v") else ""
    else:
        return None
    return candidate if _ID_RE.match(candidate) else None


def fetch_info(video_id: str) -> dict:
    opts = {"quiet": True, "skip_download": True, "noplaylist": True, "js_runtimes": {"node": {}}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    return {
        "title": info.get("title", ""),
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "duration": float(info.get("duration") or 0),
    }


def download_audio(video_id: str) -> Path:
    """Download the audio track as m4a (whisper reads it through ffmpeg)."""
    out_dir = settings.data_dir / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{video_id}.m4a"
    if target.exists():
        return target
    opts = {
        "quiet": True,
        "js_runtimes": {"node": {}},
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(out_dir / f"{video_id}.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    return target


async def fetch_info_async(video_id: str) -> dict:
    return await asyncio.to_thread(fetch_info, video_id)
