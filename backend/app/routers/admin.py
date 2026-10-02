from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.db import get_session
from app.deps import admin_user
from app.models import Invite, User
from app.services import auth

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])


class InviteIn(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


def _invite_out(invite: Invite, names: dict[int, str]) -> dict:
    now = auth.utcnow()
    state = "used" if invite.used_by else "expired" if auth.aware(invite.expires_at) <= now else "open"
    return {
        "code": invite.code, "state": state, "created_at": invite.created_at.isoformat(),
        "expires_at": invite.expires_at.isoformat(), "used_by": names.get(invite.used_by) if invite.used_by else None,
    }


def _names(session: Session) -> dict[int, str]:
    return {u.id: u.username for u in session.exec(select(User)).all()}


@router.post("/invites")
def create_invite(body: InviteIn, admin: User = Depends(admin_user), session: Session = Depends(get_session)):
    return _invite_out(auth.create_invite(session, admin.id, body.days), _names(session))


@router.get("/invites")
def list_invites(session: Session = Depends(get_session)):
    names = _names(session)
    return [_invite_out(i, names) for i in session.exec(select(Invite).order_by(col(Invite.created_at).desc())).all()]


@router.get("/users")
def list_users(session: Session = Depends(get_session)):
    return [
        {"id": u.id, "username": u.username, "is_admin": u.is_admin, "disabled": u.disabled, "created_at": u.created_at.isoformat()}
        for u in session.exec(select(User).order_by(User.id)).all()
    ]


def _set_disabled(user_id: int, disabled: bool, admin: User, session: Session) -> dict:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(404, "找不到這位使用者")
    if user.id == admin.id:
        raise HTTPException(400, "不能停用自己的帳號")
    user.disabled = disabled
    session.add(user)
    session.commit()
    if disabled:
        auth.end_all_sessions(session, user.id)
    return {"id": user.id, "disabled": user.disabled}


@router.post("/users/{user_id}/disable")
def disable_user(user_id: int, admin: User = Depends(admin_user), session: Session = Depends(get_session)):
    return _set_disabled(user_id, True, admin, session)


@router.post("/users/{user_id}/enable")
def enable_user(user_id: int, admin: User = Depends(admin_user), session: Session = Depends(get_session)):
    return _set_disabled(user_id, False, admin, session)
