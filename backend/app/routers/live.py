import asyncio
import datetime
import json
import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.auth import current_session, current_user
from app.db import SessionLocal, get_session
from app.jobs import tasks
from app.models import Course, Lecture, LecturePart
from app.routers.common import get_or_404
from app.schemas.lectures import Lecture as LectureRef
from app.schemas.live import SaveLiveRecording
from app.services import live

log = logging.getLogger("audimax.live")

# Not behind the router-wide login dependency in main.py: the WebSocket checks the session itself
# (without holding a database connection open for the whole lecture).
router = APIRouter(tags=["live"])

MIN_SAVE_SECONDS = 5


@router.websocket("/live/ws")
async def live_subtitles(ws: WebSocket, session: uuid.UUID = Query()):
    """Browser -> binary PCM16 24 kHz mono frames, and JSON {"type": "commit"} at the end of a stretch
    of speech. Server -> {"type": "item" | "delta" | "final" | "error", ...}. Reconnecting with the
    same `session` keeps appending to the same recording."""
    async with SessionLocal() as db:
        try:
            await current_session(ws, db)
        except HTTPException:
            await ws.close(code=4401)
            return
    await ws.accept()
    live.remove_stale_recordings()
    try:
        upstream = live.open_upstream()
        await upstream.__aenter__()
    except Exception as e:
        log.exception("could not open the transcription connection")
        await ws.send_json({"type": "error", "message": str(e) or "Could not reach the transcription service"})
        await ws.close()
        return

    uncommitted = 0

    async def browser_to_openai():
        nonlocal uncommitted
        with live.pcm_path(session).open("ab") as recording:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if data := message.get("bytes"):
                    recording.write(data)
                    recording.flush()
                    uncommitted += len(data)
                    await upstream.audio(data)
                elif text := message.get("text"):
                    if json.loads(text).get("type") == "commit" and uncommitted >= live.MIN_COMMIT_BYTES:
                        uncommitted = 0
                        await upstream.commit()

    async def openai_to_browser():
        async for event in upstream.events():
            await ws.send_json(event)

    tasks_ = [asyncio.create_task(browser_to_openai()), asyncio.create_task(openai_to_browser())]
    try:
        await asyncio.wait(tasks_, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks_:
            t.cancel()
        await asyncio.gather(*tasks_, return_exceptions=True)
        await upstream.__aexit__(None, None, None)
        try:
            await ws.close()
        except RuntimeError:
            pass  # already closed by the browser


@router.post("/live/{session_id}/save", response_model=LectureRef, status_code=201, dependencies=[Depends(current_user)])
async def save_live_recording(session_id: uuid.UUID, body: SaveLiveRecording, db: AsyncSession = Depends(get_session)):
    """Turn what was recorded during a live session into a lecture; the usual pipeline takes over."""
    await get_or_404(db, Course, body.course_id, "Course")
    pcm = live.pcm_path(session_id)
    if not pcm.exists() or pcm.stat().st_size < live.BYTES_PER_SECOND * MIN_SAVE_SECONDS:
        raise HTTPException(404, "There is no recording to save for this session.")

    title = body.title.strip() or f"Live {datetime.datetime.now():%Y-%m-%d %H:%M}"
    lecture = Lecture(course_id=body.course_id, title=title)
    db.add(lecture)
    await db.flush()
    filename = "live-recording.mp3"
    key = f"lectures/{lecture.id}/parts/0-{filename}"
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / filename
        await asyncio.to_thread(live.pcm_to_mp3, pcm, mp3)
        await asyncio.to_thread(storage.put_file, key, mp3)
    db.add(LecturePart(lecture_id=lecture.id, n=0, filename=filename, audio_key=key))
    await db.commit()
    pcm.unlink(missing_ok=True)
    await tasks.defer(tasks.transcribe_lecture, str(lecture.id), english=body.english)
    return LectureRef(id=lecture.id, title=lecture.title)


@router.delete("/live/{session_id}", status_code=204, dependencies=[Depends(current_user)])
async def discard_live_recording(session_id: uuid.UUID):
    live.pcm_path(session_id).unlink(missing_ok=True)
