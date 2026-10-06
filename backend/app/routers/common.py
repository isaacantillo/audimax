import uuid
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


def media_url(key: str) -> str:
    """Same-origin URL: the browser sends its session cookie, then gets redirected to R2."""
    return f"/api/media/{key}"


async def get_or_404(db: AsyncSession, model: type[T], id: uuid.UUID, what: str | None = None) -> T:
    obj = await db.get(model, id)
    if obj is None:
        raise HTTPException(404, f"{what or model.__name__} not found")
    return obj
