from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app.db import get_session
from app.models import User
from app.services import auth, ratelimit


def optional_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    return auth.user_for_token(session, request.cookies.get(auth.COOKIE))


def current_user(user: User | None = Depends(optional_user)) -> User:
    if not user:
        raise HTTPException(401, "請先登入")
    ratelimit.limit_user(user.id)
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "只有管理員可以這樣做")
    return user
