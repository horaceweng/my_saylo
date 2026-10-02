import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import engine
from app.deps import admin_user
from app.services import app_settings
from app.services.app_settings import SettingError

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(admin_user)])


class SettingsUpdate(BaseModel):
    llm_model: str | None = None
    whisper_model: str | None = None
    llm_backend: str | None = None
    cloud_base_url: str | None = Field(default=None, max_length=300)
    cloud_api_key: str | None = Field(default=None, max_length=300)
    cloud_model: str | None = Field(default=None, max_length=120)
    stt_backend: str | None = None
    stt_base_url: str | None = Field(default=None, max_length=300)
    stt_api_key: str | None = Field(default=None, max_length=300)
    stt_model: str | None = Field(default=None, max_length=120)
    fallback_local: bool | None = None


@router.get("")
def get_settings():
    return app_settings.snapshot()


@router.put("")
def put_settings(body: SettingsUpdate):
    try:
        cloud = {f: getattr(body, f) for f in app_settings.CLOUD_FIELDS}
        app_settings.update(engine, body.llm_model, body.whisper_model, cloud, body.fallback_local)
    except SettingError as e:
        raise HTTPException(400, str(e)) from e
    return app_settings.snapshot()


@router.post("/test/{target}")
async def test_connection(target: str):
    """Try the saved cloud settings: `llm` asks the model a tiny question, `stt` checks the key."""
    if target == "llm":
        return await app_settings.check_llm()
    if target == "stt":
        return await asyncio.to_thread(app_settings.check_stt)
    raise HTTPException(404, "不知道要測試什麼")
