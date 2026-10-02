from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.models import User
from app.services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class RegisterIn(LoginIn):
    code: str = Field(max_length=100)


def user_out(user: User) -> dict:
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin}


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.COOKIE, token, max_age=settings.session_days * 86400, httponly=True, samesite="lax",
        secure=settings.cookie_secure, path="/",
    )


@router.post("/login")
def login(body: LoginIn, response: Response, session: Session = Depends(get_session)):
    try:
        user = auth.authenticate(session, body.username, body.password)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e)) from e
    _set_cookie(response, auth.start_session(session, user))
    return user_out(user)


@router.post("/register")
def register(body: RegisterIn, response: Response, session: Session = Depends(get_session)):
    try:
        user = auth.register(session, body.code, body.username, body.password)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e)) from e
    _set_cookie(response, auth.start_session(session, user))
    return user_out(user)


@router.post("/logout")
def logout(request: Request, response: Response, session: Session = Depends(get_session)):
    auth.end_session(session, request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
