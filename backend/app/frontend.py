"""Serve the built web page (frontend/dist) from the same server as the API, so the app is one command."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def mount_frontend(app: FastAPI, dist: Path = FRONTEND_DIST) -> bool:
    """Add routes for the built pages. Returns False (and adds nothing) if `npm run build` has not been run.
    Call it after the API routes: every other address gets the page, and the page picks its own route."""
    index = dist / "index.html"
    if not index.exists():
        return False
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    root = dist.resolve()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def page(path: str, request: Request):
        if request.method != "GET" or path == "api" or path.startswith("api/"):
            raise HTTPException(404, "找不到")  # only pages are served here; an unknown API address is an error
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)  # favicon.svg and the like
        return FileResponse(index)  # /videos/3, /news … are pages of the app

    return True
