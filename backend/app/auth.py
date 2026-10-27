import datetime
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.db import get_session
from app.models import AuthSession, User
from app.services import geoip

COOKIE_NAME = "audimax_session"

_hasher = PasswordHasher()
# Verified against when the username is unknown, so a miss takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def check_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except VerifyMismatchError:
        return False


def new_token() -> tuple[str, str]:
    """(token to give the client, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token_from(request: HTTPConnection) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


# How often a session in use rewrites "last seen" (a new IP is recorded at once).
SEEN_EVERY = datetime.timedelta(minutes=5)


def touch(session: AuthSession, conn: HTTPConnection, now: datetime.datetime) -> bool:
    """Record where `session` is being used from. True if anything changed (the caller commits)."""
    ip = conn.client.host if conn.client else None
    user_agent = conn.headers.get("user-agent", "")[:500] or None
    if session.ip == ip and session.user_agent == user_agent and session.last_seen_at and now - session.last_seen_at < SEEN_EVERY:
        return False
    if session.ip != ip or session.location is None:
        session.location = geoip.lookup(ip)
    session.ip, session.user_agent, session.last_seen_at = ip, user_agent, now
    return True


async def current_session(
    request: HTTPConnection, db: AsyncSession = Depends(get_session)
) -> tuple[User, AuthSession]:
    token = _token_from(request)
    if token:
        row = (
            await db.execute(
                select(User, AuthSession)
                .join(AuthSession, AuthSession.user_id == User.id)
                .where(AuthSession.token_hash == hash_token(token))
            )
        ).first()
        if row:
            user, session = row
            now = datetime.datetime.now(datetime.UTC)
            if session.expires_at is None or session.expires_at > now:
                if touch(session, request, now):
                    await db.commit()
                return user, session
    raise HTTPException(401, "Not authenticated")


async def current_user(auth: tuple[User, AuthSession] = Depends(current_session)) -> User:
    return auth[0]
