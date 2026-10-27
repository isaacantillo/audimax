import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from ua_parser import parse as parse_user_agent
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    COOKIE_NAME,
    check_password,
    current_session,
    current_user,
    new_token,
    touch,
)
from app.config import settings
from app.db import get_session
from app.models import AuthSession, User
from app.ratelimit import FailureLimiter
from app.schemas.login import ApiTokenRequest, ApiTokenResponse, LoginRequest, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
login_failures = FailureLimiter()


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_session)):
    key = request.client.host if request.client else "unknown"
    if login_failures.blocked(key):
        raise HTTPException(429, "Too many failed attempts. Try again later.", headers={"Retry-After": str(login_failures.retry_after(key))})
    user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if not check_password(user.password_hash if user else None, body.password) or user is None:
        login_failures.fail(key)
        raise HTTPException(401, "Wrong username or password")
    login_failures.reset(key)

    token, token_hash = new_token()
    now = datetime.datetime.now(datetime.UTC)
    session = AuthSession(user_id=user.id, token_hash=token_hash, kind="browser", expires_at=now + datetime.timedelta(days=settings.session_days))
    touch(session, request, now)
    db.add(session)
    await db.commit()

    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return UserOut(id=user.id, username=user.username, is_admin=user.is_admin)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    auth: tuple[User, AuthSession] = Depends(current_session),
    db: AsyncSession = Depends(get_session),
):
    await db.execute(delete(AuthSession).where(AuthSession.id == auth[1].id))
    await db.commit()
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(current_user)):
    return UserOut(id=user.id, username=user.username, is_admin=user.is_admin)


def describe_device(user_agent: str | None) -> str:
    """"Chrome on Mac OS X", "Mobile Safari on iOS · iPhone", "Shortcuts on iOS"."""
    if not user_agent:
        return "Unknown device"
    parsed = parse_user_agent(user_agent)
    browser = parsed.user_agent.family if parsed.user_agent else None
    os = parsed.os.family if parsed.os else None
    device = parsed.device.family if parsed.device else None
    text = " on ".join(x for x in (browser, os) if x and x != "Other") or user_agent[:60]
    if device and device not in {"Other", "Mac", "iOS-Device", "Generic Smartphone"} and device != os:
        text += f" · {device}"
    return text


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    auth: tuple[User, AuthSession] = Depends(current_session),
    db: AsyncSession = Depends(get_session),
):
    """Your signed-in devices and API tokens; the admin sees everyone's. Expired sessions are left out."""
    user, current = auth
    now = datetime.datetime.now(datetime.UTC)
    query = (
        select(AuthSession, User.username)
        .join(User, User.id == AuthSession.user_id)
        .where((AuthSession.expires_at.is_(None)) | (AuthSession.expires_at > now))
        .order_by(User.username, AuthSession.last_seen_at.desc().nulls_last(), AuthSession.created_at.desc())
    )
    if not user.is_admin:
        query = query.where(AuthSession.user_id == user.id)
    return [
        SessionOut(
            id=s.id, username=username, kind=s.kind, name=s.name, device=describe_device(s.user_agent),
            ip=s.ip, location=s.location, created_at=s.created_at, last_seen_at=s.last_seen_at, current=s.id == current.id,
        )
        for s, username in (await db.execute(query)).all()
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    response: Response,
    auth: tuple[User, AuthSession] = Depends(current_session),
    db: AsyncSession = Depends(get_session),
):
    """Log a device out (or revoke an API token). Your own, or anyone's for the admin."""
    user, current = auth
    target = await db.get(AuthSession, session_id)
    if target is None or not (user.is_admin or target.user_id == user.id):
        raise HTTPException(404, "Session not found")
    await db.delete(target)
    await db.commit()
    if target.id == current.id:
        response.delete_cookie(COOKIE_NAME)


@router.post("/tokens", response_model=ApiTokenResponse)
async def create_api_token(
    body: ApiTokenRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
):
    """Long-lived bearer token, e.g. for the phone Shortcut. Returned once, stored hashed."""
    token, token_hash = new_token()
    db.add(AuthSession(user_id=user.id, token_hash=token_hash, kind="api", name=body.name))
    await db.commit()
    return ApiTokenResponse(name=body.name, token=token)
