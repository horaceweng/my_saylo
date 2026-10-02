"""Accounts, invites and login sessions."""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from pwdlib import PasswordHash
from sqlmodel import Session, col, delete, select, update

from app.config import settings
from app.models import AuthSession, Book, BookProgress, Invite, Recording, SavedPhrase, User

COOKIE = "session"
_hasher = PasswordHash.recommended()
# Checked when the username does not exist, so a wrong name and a wrong password take equally long.
_DUMMY_HASH = _hasher.hash("not-a-real-password")
_USERNAME = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD = 8


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    """SQLite hands datetimes back without their time zone; everything here is UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def normalize_username(username: str) -> str:
    name = username.strip().lower()
    if not _USERNAME.match(name):
        raise AuthError("帳號需為 3–32 個英文字母、數字、底線、句點或連字號")
    return name


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"密碼至少 {MIN_PASSWORD} 個字元")
    if len(password) > 200:
        raise AuthError("密碼太長")


def create_user(session: Session, username: str, password: str, is_admin: bool = False) -> User:
    name = normalize_username(username)
    check_password_rules(password)
    if session.exec(select(User).where(User.username == name)).first():
        raise AuthError("這個帳號名稱已被使用", 409)
    user = User(username=name, password_hash=hash_password(password), is_admin=is_admin)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def claim_ownerless_rows(session: Session, user_id: int) -> int:
    """Phrases and recordings from before accounts existed belong to the first admin."""
    total = 0
    for model in (SavedPhrase, Recording):
        result = session.exec(update(model).where(col(model.user_id).is_(None)).values(user_id=user_id))
        total += result.rowcount or 0
    # The one reading position that used to be shared by everyone goes to the first admin; once moved it is cleared,
    # so running this again for another admin hands over nothing.
    for book in session.exec(select(Book).where((Book.last_chapter != 0) | (Book.last_paragraph != 0))).all():
        if session.get(BookProgress, (user_id, book.id)) is None:
            session.add(BookProgress(user_id=user_id, book_id=book.id, last_chapter=book.last_chapter, last_paragraph=book.last_paragraph))
            total += 1
        book.last_chapter = book.last_paragraph = 0
        session.add(book)
    session.commit()
    return total


def authenticate(session: Session, username: str, password: str) -> User:
    user = session.exec(select(User).where(User.username == username.strip().lower())).first()
    ok = _hasher.verify(password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise AuthError("帳號或密碼不正確", 401)
    if user.disabled:
        raise AuthError("這個帳號已被停用", 403)
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    session.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, created_at=now, last_seen=now,
                            expires_at=now + timedelta(days=settings.session_days)))
    session.commit()
    return token


def user_for_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = session.get(AuthSession, _token_hash(token))
    if not row:
        return None
    now = utcnow()
    if aware(row.expires_at) <= now:
        session.delete(row)
        session.commit()
        return None
    user = session.get(User, row.user_id)
    if not user or user.disabled:
        return None
    if now - aware(row.last_seen) > timedelta(minutes=10):  # not on every request: it would be a write per call
        row.last_seen = now
        session.add(row)
        session.commit()
    return user


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.exec(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        session.commit()


def end_all_sessions(session: Session, user_id: int) -> None:
    session.exec(delete(AuthSession).where(AuthSession.user_id == user_id))
    session.commit()


def create_invite(session: Session, created_by: int, days: int | None = None) -> Invite:
    invite = Invite(code=secrets.token_urlsafe(16), created_by=created_by,
                    expires_at=utcnow() + timedelta(days=days or settings.invite_days))
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return invite


def register(session: Session, code: str, username: str, password: str) -> User:
    invite = session.get(Invite, code.strip())
    if not invite or invite.used_by is not None or aware(invite.expires_at) <= utcnow():
        raise AuthError("邀請碼無效、已被使用或已過期", 400)
    user = create_user(session, username, password)
    # Claim the code with a conditional update so two simultaneous sign-ups cannot both use it.
    claimed = session.exec(
        update(Invite).where(Invite.code == invite.code, col(Invite.used_by).is_(None)).values(used_by=user.id)
    ).rowcount
    if claimed != 1:
        session.delete(user)
        session.commit()
        raise AuthError("邀請碼無效、已被使用或已過期", 400)
    session.commit()
    return user
