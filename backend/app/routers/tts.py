import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services import tts
from app.services.tts import TTSError

router = APIRouter(prefix="/api/tts", tags=["tts"])


class SpeakIn(BaseModel):
    text: str = Field(max_length=2000)
    voice: str = tts.DEFAULT_VOICE


@router.get("/status")
def status():
    """Can the natural voice be used, and if not, why not."""
    issues = tts.problems()
    return {
        "available": not issues,
        "problems": issues,
        "model_downloaded": tts.model_downloaded(),
        "default_voice": tts.DEFAULT_VOICE,
        "voices": [{"id": v.id, "label": v.label} for v in tts.VOICES],
    }


@router.post("/speak")
async def speak(body: SpeakIn):
    """The spoken audio (mp3) of a short text. The same text and voice is only ever made once."""
    try:
        path = await asyncio.to_thread(tts.speak_file, body.text, body.voice)
    except TTSError as e:
        raise HTTPException(400, str(e)) from e
    return FileResponse(path, media_type="audio/mpeg")
