import asyncio
import logging
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.frontend import mount_frontend
from app.db import engine, init_db
from app.routers import ai, books, dictionary, media, news, phrases, podcasts, settings as settings_router, shadowing, tts
from app.services import resegment, app_settings
from app.services import pipeline

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
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
for r in (media.router, podcasts.router, books.router, news.router, dictionary.router, ai.router, phrases.router, shadowing.router, settings_router.router, tts.router):
    app.include_router(r)


@app.get("/api/health")
async def health():
    """What the page needs to know to say "start Ollama", "enter an API key" or "the dictionary is missing"."""
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
