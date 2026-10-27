import mimetypes
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.auth import current_user
from app.db import get_session
from app.models import User
from app.routers.common import owned_lecture

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}", include_in_schema=False)
async def media(key: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    """Lecture audio. R2: redirect to a short-lived signed URL (supports seeking). Local: stream."""
    parts = key.split("/")
    if len(parts) < 3 or parts[0] != "lectures" or ".." in parts:
        raise HTTPException(404)
    try:
        lecture_id = uuid.UUID(parts[1])
    except ValueError:
        raise HTTPException(404) from None
    await owned_lecture(db, lecture_id, user)
    url = storage.presigned_url(key)
    if url:
        return RedirectResponse(url, status_code=307)
    path = storage.local_path(key)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
