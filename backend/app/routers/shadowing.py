import asyncio
import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, col, select

from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.models import Media, Recording, Segment, User
from app.services import prompts, shadowing, usage
from app.services.llm import LLMError, chat_json, make_provider
from app.services.partial_json import parse_partial

router = APIRouter(prefix="/api", tags=["shadowing"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_SECONDS = 90


def get_feedback_provider():
    return make_provider()


def _dir(name: str) -> Path:
    path = settings.data_dir / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _out(rec: Recording) -> dict:
    return {
        "id": rec.id, "segment_id": rec.segment_id, "duration": rec.duration, "heard_text": rec.heard_text,
        "score": rec.score, "tokens": json.loads(rec.diff_json),
        "feedback": shadowing.finish_feedback(json.loads(rec.feedback_json)) if rec.feedback_json else None,
        "created_at": rec.created_at.isoformat(),
    }


def _segment(session: Session, segment_id: int) -> Segment:
    seg = session.get(Segment, segment_id)
    if not seg:
        raise HTTPException(404, "找不到這個句子")
    return seg


@router.get("/segments/{segment_id}/audio")
def sentence_audio(segment_id: int, session: Session = Depends(get_session)):
    """The original speaker's audio for this one sentence (cut from the downloaded audio and cached)."""
    seg = _segment(session, segment_id)
    media = session.get(Media, seg.media_id)
    source = Path(media.audio_path) if media and media.audio_path else None
    if not source or not source.exists():
        raise HTTPException(404, "找不到原音檔，請重新處理這個影片")
    clip = _dir("clips") / f"seg{seg.id}_{int(seg.start * 1000)}_{int(seg.end * 1000)}.wav"
    if not clip.exists():
        try:
            shadowing.extract_clip(source, seg.start, seg.end, clip)
        except shadowing.AudioError as e:
            raise HTTPException(500, f"切割原音失敗：{e}") from e
    return FileResponse(clip, media_type="audio/wav")


@router.post("/segments/{segment_id}/recordings")
async def upload_recording(segment_id: int, file: UploadFile, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Take a recording of the learner, recognise it and compare it word by word with the sentence."""
    seg = _segment(session, segment_id)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(400, "沒有收到錄音")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "錄音檔太大")

    folder = _dir(f"recordings/{user.id}")  # one folder per learner; older files stay where the database says
    token = uuid.uuid4().hex
    raw, wav = folder / f"{token}.upload", folder / f"{token}.wav"
    try:
        raw.write_bytes(data)
        try:
            await asyncio.to_thread(shadowing.to_wav16k, raw, wav)
            duration, loudness = shadowing.wav_stats(wav)
        except (shadowing.AudioError, OSError, EOFError) as e:
            raise HTTPException(400, f"無法讀取這段錄音：{e}") from e
        if duration > MAX_SECONDS:
            raise HTTPException(413, f"錄音太長（超過 {MAX_SECONDS} 秒），請只錄這一句")
        if loudness < shadowing.SILENT_RMS:
            raise HTTPException(422, "沒有錄到聲音，請確認麥克風有開啟、音量足夠")
        usage.charge_ai(session, user)  # speech recognition on this Mac is the costly part
        try:
            words = await asyncio.to_thread(shadowing.transcribe_recording, wav)
        except shadowing.TranscriberBusy as e:
            raise HTTPException(503, str(e)) from e
    except Exception:
        wav.unlink(missing_ok=True)
        raise
    finally:
        raw.unlink(missing_ok=True)

    result = shadowing.compare(seg.text, words)
    rec = Recording(
        segment_id=seg.id, user_id=user.id, file_path=str(wav), duration=round(duration, 2), score=result.score,
        heard_text=" ".join(w.text.strip() for w in words), diff_json=json.dumps(result.to_json_list(), ensure_ascii=False),
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return _out(rec)


@router.get("/segments/{segment_id}/recordings")
def list_recordings(segment_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    _segment(session, segment_id)
    rows = session.exec(select(Recording).where(Recording.segment_id == segment_id, Recording.user_id == user.id).order_by(col(Recording.created_at).desc())).all()
    return [_out(r) for r in rows]


def _recording(session: Session, recording_id: int, user: User) -> Recording:
    rec = session.get(Recording, recording_id)
    if not rec or rec.user_id != user.id:  # someone else's recording looks the same as a missing one
        raise HTTPException(404, "找不到這筆錄音")
    return rec


@router.get("/recordings/{recording_id}/audio")
def recording_audio(recording_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    rec = _recording(session, recording_id, user)
    if not Path(rec.file_path).exists():
        raise HTTPException(404, "錄音檔已不存在")
    return FileResponse(rec.file_path, media_type="audio/wav")


@router.delete("/recordings/{recording_id}")
def delete_recording(recording_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    rec = _recording(session, recording_id, user)
    Path(rec.file_path).unlink(missing_ok=True)
    session.delete(rec)
    session.commit()
    return {"ok": True}


@router.post("/recordings/{recording_id}/feedback/stream")
async def feedback_stream(
    recording_id: int, session: Session = Depends(get_session), provider=Depends(get_feedback_provider), user: User = Depends(current_user)
):
    """AI comments on one attempt, streamed as newline-delimited JSON (partial… then done or error)."""
    rec = _recording(session, recording_id, user)
    seg = _segment(session, rec.segment_id)
    bind, saved = session.get_bind(), rec.feedback_json
    reference, heard, score = seg.text, rec.heard_text, rec.score
    if not saved:
        usage.charge_ai(session, user)
    facts = shadowing.Comparison(
        [shadowing.Token(**t) for t in json.loads(rec.diff_json)], score, {}
    ).facts()

    def line(event: dict) -> str:
        return json.dumps(event, ensure_ascii=False) + "\n"

    async def events():
        if saved:
            yield line({"type": "done", "data": shadowing.finish_feedback(json.loads(saved))})
            return
        user = prompts.feedback_user_prompt(reference, heard, score, facts)
        text, last = "", 0.0
        try:
            async for chunk in provider.stream(prompts.FEEDBACK_SYSTEM, user, json_mode=True):
                text += chunk
                if time.monotonic() - last >= 0.08:
                    last = time.monotonic()
                    partial = parse_partial(text)
                    if partial is not None:
                        yield line({"type": "partial", "data": shadowing.sanitize_feedback(partial)})
            try:
                result = prompts.ShadowFeedback.model_validate(json.loads(text))
            except ValueError:
                result = await chat_json(provider, prompts.FEEDBACK_SYSTEM, user, prompts.ShadowFeedback)
        except LLMError as e:
            yield line({"type": "error", "message": str(e)})
            return
        final = shadowing.finish_feedback(result.model_dump())
        with Session(bind) as s:
            row = s.get(Recording, recording_id)
            if row:
                row.feedback_json = json.dumps(final, ensure_ascii=False)
                s.add(row)
                s.commit()
        yield line({"type": "done", "data": final})

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
