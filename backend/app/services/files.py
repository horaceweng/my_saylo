"""Serving files from the data folder: the path must stay inside the folder it belongs to."""

from pathlib import Path

from app.config import settings


def inside(path: str | Path | None, folder: str) -> Path | None:
    """The real file at `path` if it lies inside data/<folder>, else None. Symlinks and ".." are resolved first, so a
    database row (or a bug) that points elsewhere can never make the server hand out some other file."""
    if not path:
        return None
    try:
        target, root = Path(path).resolve(), (settings.data_dir / folder).resolve()
    except (OSError, ValueError):
        return None
    return target if root in target.parents and target.is_file() else None
