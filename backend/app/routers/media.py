import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app import storage

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}", include_in_schema=False)
async def media(key: str):
    """Lecture audio. R2: redirect to a short-lived signed URL (supports seeking). Local: stream."""
    if not key.startswith("lectures/") or ".." in key:
        raise HTTPException(404)
    url = storage.presigned_url(key)
    if url:
        return RedirectResponse(url, status_code=307)
    path = storage.local_path(key)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
