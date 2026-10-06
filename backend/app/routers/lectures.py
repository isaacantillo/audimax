import re
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.db import get_session
from app.jobs import pipeline, tasks
from app.models import Chunk, Course, Lecture, LecturePart, Paragraph, Unit
from app.routers.common import get_or_404, media_url
from app.schemas import lectures as s
from app.schemas.enums import LectureStatus
from app.schemas.lectures import Lecture as LectureRef
from app.schemas.lectures import LectureSummary

router = APIRouter(tags=["lectures"])

AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".mp4", ".webm", ".opus"}
READY_FOR_ENGLISH = {"ready", "english_ready", "failed"}


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "file"


@router.post("/lectures", response_model=LectureRef, status_code=201)
async def create_lecture(
    course_id: uuid.UUID = Form(),
    title: str = Form(""),
    english: bool = Form(False),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_session),
):
    """Upload one lecture as one or more recordings (they are joined in filename order)."""
    await get_or_404(db, Course, course_id, "Course")
    bad = [f.filename for f in files if Path(f.filename or "").suffix.lower() not in AUDIO_SUFFIXES]
    if not files or bad:
        raise HTTPException(422, f"Not audio files: {bad or 'no files given'}")

    ordered = sorted(files, key=lambda f: f.filename or "")
    lecture = Lecture(course_id=course_id, title=title.strip() or re.sub(r"_\d+$", "", Path(ordered[0].filename or "Lecture").stem))
    db.add(lecture)
    await db.flush()
    for n, upload in enumerate(ordered):
        filename = _safe(upload.filename or f"part{n}")
        key = f"lectures/{lecture.id}/parts/{n}-{filename}"
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as tmp:
            while chunk := await upload.read(1024 * 1024):
                tmp.write(chunk)
            tmp.flush()
            storage.put_file(key, Path(tmp.name))
        db.add(LecturePart(lecture_id=lecture.id, n=n, filename=filename, audio_key=key))
    await db.commit()
    await tasks.defer(tasks.transcribe_lecture, str(lecture.id), english=english)
    return LectureRef(id=lecture.id, title=lecture.title)


def _part_at(parts: list[LecturePart], t: float) -> LecturePart:
    return max((p for p in parts if p.offset <= t), key=lambda p: p.offset, default=parts[0])


@router.get("/lectures/{lecture_id}", response_model=s.TranscriptDetails)
async def get_lecture(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    lecture = await get_or_404(db, Lecture, lecture_id, "Lecture")
    parts = list((await db.execute(select(LecturePart).where(LecturePart.lecture_id == lecture_id).order_by(LecturePart.n))).scalars())
    units = list((await db.execute(select(Unit).where(Unit.lecture_id == lecture_id).order_by(Unit.n))).scalars())

    english = None
    chunks = list((await db.execute(select(Chunk).where(Chunk.lecture_id == lecture_id).order_by(Chunk.n))).scalars())
    if chunks:
        paragraphs = (await db.execute(select(Paragraph).where(Paragraph.lecture_id == lecture_id).order_by(Paragraph.chunk_n, Paragraph.n))).scalars()
        by_chunk: dict[uuid.UUID, list[s.EnglishParagraph]] = {}
        starts = {u.n: u.start for u in units}
        for p in paragraphs:
            t = starts.get(p.first_unit, 0.0)
            part = _part_at(parts, t)
            by_chunk.setdefault(p.chunk_id, []).append(
                s.EnglishParagraph(
                    id=f"{p.chunk_n:02d}.{p.n:02d}", text=p.text, start=p.start, end=p.end,
                    source_start=t, source_part=part.n, source_part_start=round(t - part.offset, 2),
                )
            )
        english = s.EnglishLecture(
            audio_url=media_url(lecture.english_audio_key) if lecture.english_audio_key else None,
            duration_seconds=int(lecture.english_duration),
            tts_provider=lecture.tts_provider,
            chunks=[
                s.EnglishChunk(n=c.n, title=c.title, status=c.status, verified=c.verified, attempts=c.attempts, paragraphs=by_chunk.get(c.id, []))
                for c in chunks
            ],
        )

    return s.TranscriptDetails(
        id=lecture.id,
        course_id=lecture.course_id,
        title=lecture.title,
        status=LectureStatus(lecture.status),
        error=lecture.error,
        audio_url=media_url(parts[0].audio_key) if parts else "",
        duration_seconds=int(lecture.duration),
        parts=[s.LecturePart(n=p.n, filename=p.filename, offset=p.offset, duration=p.duration, audio_url=media_url(p.audio_key)) for p in parts],
        transcript_segments=[s.TranscriptSegment(start=u.start, end=u.end, text_original=u.text_de, text_translated=u.text_en) for u in units],
        english=english,
    )


@router.delete("/lectures/{lecture_id}", status_code=204)
async def delete_lecture(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    lecture = await get_or_404(db, Lecture, lecture_id, "Lecture")
    await db.delete(lecture)
    await db.commit()
    storage.delete_prefix(f"lectures/{lecture_id}/")


@router.get("/lectures/{lecture_id}/summary", response_model=LectureSummary)
async def get_summary(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    l = await get_or_404(db, Lecture, lecture_id, "Lecture")
    return LectureSummary(
        id=l.id, title=l.title, summary=l.summary or "", status=LectureStatus(l.status),
        duration_seconds=int(l.duration), date=l.date, has_english=l.english_audio_key is not None,
    )


@router.post("/lectures/{lecture_id}/english", status_code=202)
async def create_english(lecture_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """Build (or rebuild from scratch) the English re-performed lecture. Costs TTS money."""
    l = await get_or_404(db, Lecture, lecture_id, "Lecture")
    if l.status not in READY_FOR_ENGLISH or not l.duration:
        raise HTTPException(409, f"The lecture is {l.status}; wait until it is ready.")
    unit_count = len((await db.execute(select(Unit.id).where(Unit.lecture_id == lecture_id).limit(1))).all())
    if not unit_count:
        raise HTTPException(409, "The lecture has no transcript yet.")
    l.status, l.error = "chunking", None
    await db.commit()
    await tasks.defer(tasks.english_plan, str(lecture_id))
    return {"status": "queued"}


@router.post("/lectures/{lecture_id}/english/chunks/{n}/rerun", status_code=202)
async def rerun_chunk(lecture_id: uuid.UUID, n: int, db: AsyncSession = Depends(get_session)):
    """Rewrite one chunk; only its changed paragraphs are re-voiced, then the audio is re-stitched."""
    l = await get_or_404(db, Lecture, lecture_id, "Lecture")
    if l.status not in {"english_ready", "failed"}:
        raise HTTPException(409, f"The lecture is {l.status}; wait until it finishes.")
    try:
        await pipeline.reset_chunk(lecture_id, n)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await db.refresh(l)
    l.status, l.error = "scripting", None
    await db.commit()
    await tasks.defer(tasks.english_write, str(lecture_id))
    return {"status": "queued"}
