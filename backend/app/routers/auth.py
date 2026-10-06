import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    COOKIE_NAME,
    check_password,
    current_session,
    current_user,
    new_token,
)
from app.config import settings
from app.db import get_session
from app.models import AuthSession, User
from app.ratelimit import FailureLimiter
from app.schemas.login import ApiTokenRequest, ApiTokenResponse, LoginRequest, UserOut

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
    expires = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=settings.session_days)
    db.add(AuthSession(user_id=user.id, token_hash=token_hash, kind="browser", expires_at=expires))
    await db.commit()

    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return UserOut(id=user.id, username=user.username)


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
    return UserOut(id=user.id, username=user.username)


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
