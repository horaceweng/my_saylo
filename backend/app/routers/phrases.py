from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, col, or_, select

from app.db import get_session
from app.deps import current_user
from app.models import SavedPhrase, User
from app.services import srs

router = APIRouter(prefix="/api/phrases", tags=["phrases"])


class PhraseIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    context_sentence: str = Field(default="", max_length=2000)
    translation: str = Field(default="", max_length=2000)
    note: str = Field(default="", max_length=5000)
    source_kind: str = Field(default="video", max_length=20)
    source_id: int | None = None
    timestamp: float = 0


@router.post("")
def save_phrase(body: PhraseIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    text = body.text.strip()
    dup = session.exec(
        select(SavedPhrase).where(SavedPhrase.user_id == user.id, SavedPhrase.text == text, SavedPhrase.source_id == body.source_id)
    ).first()
    if dup:
        return dup
    phrase = SavedPhrase(**{**body.model_dump(), "text": text, "user_id": user.id})
    session.add(phrase)
    session.commit()
    session.refresh(phrase)
    return phrase


@router.get("")
def list_phrases(q: str = "", session: Session = Depends(get_session), user: User = Depends(current_user)):
    stmt = select(SavedPhrase).where(SavedPhrase.user_id == user.id).order_by(col(SavedPhrase.created_at).desc())
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(col(SavedPhrase.text).like(like), col(SavedPhrase.translation).like(like)))
    return session.exec(stmt).all()


class ReviewIn(BaseModel):
    grade: int = Field(ge=0, le=3)  # 0 forgot, 1 hard, 2 remembered, 3 easy


@router.get("/review")
def phrases_to_review(limit: int = 20, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """The phrases whose time has come, oldest first, plus how many are waiting in all."""
    now = srs.utcnow()
    due = col(SavedPhrase.due_at) <= now
    cards = session.exec(select(SavedPhrase).where(SavedPhrase.user_id == user.id, due).order_by(col(SavedPhrase.due_at)).limit(max(1, min(limit, 100)))).all()
    everything = session.exec(select(SavedPhrase).where(SavedPhrase.user_id == user.id)).all()
    upcoming = [p.due_at for p in everything if p.due_at > now]
    return {
        "cards": cards, "due_count": sum(1 for p in everything if p.due_at <= now), "total": len(everything),
        "next_due": min(upcoming).isoformat() if upcoming else None,
    }


@router.post("/{phrase_id}/review")
def review_phrase(phrase_id: int, body: ReviewIn, session: Session = Depends(get_session), user: User = Depends(current_user)):
    """Record how a review went and set when the phrase comes back."""
    phrase = session.get(SavedPhrase, phrase_id)
    if not phrase or phrase.user_id != user.id:
        raise HTTPException(404, "找不到這個片語")
    card, due = srs.schedule(srs.Card(phrase.reps, phrase.interval_days, phrase.ease, phrase.lapses), body.grade)
    phrase.reps, phrase.interval_days, phrase.ease, phrase.lapses, phrase.due_at = card.reps, card.interval_days, card.ease, card.lapses, due
    session.add(phrase)
    session.commit()
    session.refresh(phrase)
    return phrase


@router.delete("/{phrase_id}")
def delete_phrase(phrase_id: int, session: Session = Depends(get_session), user: User = Depends(current_user)):
    phrase = session.get(SavedPhrase, phrase_id)
    if not phrase or phrase.user_id != user.id:
        raise HTTPException(404, "找不到這個片語")
    session.delete(phrase)
    session.commit()
    return {"ok": True}
