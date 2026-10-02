"""How much room is left. New media and books are refused when the volume holding `data/` is nearly full, and the
admin page shows the size of `data/`. Walking the audio folders can be slow, so the size is cached for a few minutes."""

import os
import shutil
import time

from fastapi import HTTPException

from app.config import settings

GB = 1024**3
SIZE_CACHE_SECONDS = 300

_size_cache: tuple[float, int] | None = None


def free_bytes() -> int:
    path = settings.data_dir if settings.data_dir.exists() else settings.data_dir.parent
    return shutil.disk_usage(path).free


def _walk_size() -> int:
    total = 0
    for root, _dirs, names in os.walk(settings.data_dir):
        for name in names:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass  # vanished while walking
    return total


def data_size_bytes() -> int:
    """Size of `data/`, recomputed at most every SIZE_CACHE_SECONDS."""
    global _size_cache
    now = time.monotonic()
    if _size_cache is None or now - _size_cache[0] > SIZE_CACHE_SECONDS:
        _size_cache = (now, _walk_size())
    return _size_cache[1]


def reset_cache() -> None:
    global _size_cache
    _size_cache = None


def is_low() -> bool:
    return free_bytes() < settings.min_free_disk_gb * GB


def require_space() -> None:
    """Refuse (for everyone, admins included) while the disk is nearly full."""
    if is_low():
        free_gb = free_bytes() / GB
        raise HTTPException(507, f"主機磁碟空間不足（剩 {free_gb:.1f} GB，低於 {settings.min_free_disk_gb:g} GB），暫時不能新增影片、音檔或書籍，請通知管理員")


def summary() -> dict:
    free = free_bytes()
    return {
        "data_bytes": data_size_bytes(), "free_bytes": free,
        "min_free_bytes": int(settings.min_free_disk_gb * GB), "low": free < settings.min_free_disk_gb * GB,
    }
