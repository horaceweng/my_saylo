import asyncio
import logging
import re
import shutil
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlmodel import Session, select

from app.config import settings
from app.frontend import mount_frontend
from app.db import engine, init_db
from app.deps import current_user, optional_user
from app.models import User
from app.security import SecurityHeaders
from app.routers import admin, ai, auth, books, dictionary, media, news, phrases, podcasts, settings as settings_router, shadowing, tts
from app.services import resegment, app_settings
from app.services import pipeline

log = logging.getLogger("uvicorn.error")

# The page asks these on a timer (health every 15 s, media lists/updates every few seconds while a job runs), so
# their successful requests would bury everything else in the terminal. Failures still show.
_POLLED = re.compile(r"^/api/(health|media(\?.*)?|media/\d+/updates(\?.*)?)$")


class _QuietPolling(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _client, method, path, _version, status = args
        return not (method == "GET" and isinstance(status, int) and status < 300 and _POLLED.match(str(path)))


logging.getLogger("uvicorn.access").addFilter(_QuietPolling())


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with Session(engine) as s:
        if not s.exec(select(User)).first():
            log.warning("no user exists yet: nobody can log in. Create the first admin with `uv run python scripts/create_admin.py <name>`")
    app_settings.load_overrides(engine)
    news.ensure_default_feeds()
    regraded = books.regrade_all(engine)
    if regraded:
        log.info("graded %d saved books/articles again (new grading method)", regraded)
    regraded_media = media.regrade_media(engine)
    if regraded_media:
        log.info("graded %d saved videos/podcasts again (new grading method)", regraded_media)
    recut = resegment.resegment_all(engine)
    if recut:
        log.info("cut the sentences of videos %s again (new rules); their new sentences are being translated", recut)
    # Jobs cut short by the last shutdown continue on their own, from what they had already saved.
    resumed = pipeline.resume_unfinished()
    if resumed:
        log.info("resuming unfinished media jobs: %s", resumed)
    yield


app = FastAPI(title="English Lab", lifespan=lifespan)
app.add_middleware(SecurityHeaders)  # no CORS middleware: the page and the API share one origin
app.include_router(auth.router)  # the only router open to everyone
# Everything else needs a login; settings and admin routers ask for an admin on top (see their own dependencies).
for r in (media.router, podcasts.router, books.router, news.router, dictionary.router, ai.router, phrases.router, shadowing.router, settings_router.router, tts.router, admin.router):
    app.include_router(r, dependencies=[Depends(current_user)])


@app.get("/api/health")
async def health(user: User | None = Depends(optional_user)):
    """What the page needs to know to say "start Ollama", "enter an API key" or "the dictionary is missing".
    Without a login it only says the server is up."""
    if not user:
        return {"ok": True}
    cloud = settings.llm_backend == "cloud"
    models = None if cloud else await asyncio.to_thread(app_settings.installed_llm_models)
    return {
        "ok": True,
        "llm_backend": settings.llm_backend,
        "stt_backend": settings.stt_backend,
        "cloud_configured": bool(settings.cloud_base_url and settings.cloud_model and (settings.cloud_api_key or app_settings._is_local_address(settings.cloud_base_url))),
        "stt_configured": bool(settings.stt_base_url and settings.stt_model),
        "ollama": cloud or models is not None,  # not needed when the cloud does the work
        "llm_model": settings.active_llm_model,
        "llm_model_installed": cloud or (models is not None and settings.llm_model in {m["name"] for m in models}),
        "dict": settings.dict_db_path.exists(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }


mount_frontend(app)  # last, so that the API routes above win
