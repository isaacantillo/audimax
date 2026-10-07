"""The stages of lecture processing as plain async functions. app/jobs/tasks.py wraps each in a
queue task that defers the next stage; tests call them directly.

Every stage is idempotent: it looks at what already exists in the DB and only does what's missing,
so a retry or a chunk rerun redoes only the affected part. A DB session is never held open across
an AI call."""

import asyncio
import functools
import logging
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import delete, select, update

from app import storage
from app.db import SessionLocal
from app.models import (
    Chunk,
    GlossaryTerm,
    Lecture,
    LecturePart,
    Paragraph,
)
from app.models import (
    Unit as UnitRow,
)
from app.services import english_lecture as el
from app.services import summary as summary_service
from app.services.transcription import Unit, atranscribe, atranslate, build_units

log = logging.getLogger("audimax.pipeline")
CONCURRENCY = 4


def stage(fn):
    """On failure mark the lecture failed with the reason (the Activity page shows it), then re-raise
    so the queue can retry."""

    @functools.wraps(fn)
    async def wrapper(lecture_id: uuid.UUID, *args, **kwargs):
        try:
            return await fn(lecture_id, *args, **kwargs)
        except Exception as exc:
            log.exception("%s failed for lecture %s", fn.__name__, lecture_id)
            async with SessionLocal() as db:
                await db.execute(
                    update(Lecture).where(Lecture.id == lecture_id).values(status="failed", error=f"{fn.__name__}: {exc}"[:1000])
                )
                await db.commit()
            raise

    return wrapper


async def set_status(lecture_id: uuid.UUID, status: str) -> None:
    async with SessionLocal() as db:
        await db.execute(update(Lecture).where(Lecture.id == lecture_id).values(status=status, error=None))
        await db.commit()


async def _gather(coros):
    sem = asyncio.Semaphore(CONCURRENCY)

    async def run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))


async def _units(lecture_id: uuid.UUID) -> list[UnitRow]:
    async with SessionLocal() as db:
        return list((await db.execute(select(UnitRow).where(UnitRow.lecture_id == lecture_id).order_by(UnitRow.n))).scalars())


def _as_units(rows: list[UnitRow]) -> list[Unit]:
    return [Unit(r.n, r.start, r.end, r.text_de) for r in rows]


# ---------- original lecture: transcribe -> translate -> summarize ----------

@stage
async def run_transcribe(lecture_id: uuid.UUID) -> None:
    await set_status(lecture_id, "transcribing")
    async with SessionLocal() as db:
        parts = list((await db.execute(select(LecturePart).where(LecturePart.lecture_id == lecture_id).order_by(LecturePart.n))).scalars())

    async def one(part: LecturePart) -> None:
        if part.transcript is not None:
            return
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / part.filename
            await asyncio.to_thread(storage.get_to_path, part.audio_key, path)
            data = await atranscribe(path)
        duration = float(data.get("duration") or (data["words"][-1]["end"] if data.get("words") else 0))
        async with SessionLocal() as db:
            await db.execute(update(LecturePart).where(LecturePart.id == part.id).values(transcript=data, duration=duration))
            await db.commit()

    # Two at a time: each upload can be large and the provider call is slow.
    sem = asyncio.Semaphore(2)

    async def limited(part):
        async with sem:
            await one(part)

    await asyncio.gather(*(limited(p) for p in parts))

    async with SessionLocal() as db:
        parts = list((await db.execute(select(LecturePart).where(LecturePart.lecture_id == lecture_id).order_by(LecturePart.n))).scalars())
        offset = 0.0
        for part in parts:
            part.offset = offset
            offset += part.duration
        await db.execute(update(Lecture).where(Lecture.id == lecture_id).values(duration=offset, status="transcribed", error=None))
        await db.commit()


@stage
async def run_translate(lecture_id: uuid.UUID) -> None:
    await set_status(lecture_id, "translating")
    async with SessionLocal() as db:
        parts = list((await db.execute(select(LecturePart).where(LecturePart.lecture_id == lecture_id).order_by(LecturePart.n))).scalars())
        raw = [{"offset": p.offset, "transcript": p.transcript} for p in parts]
    units = build_units(raw)
    if not units:
        raise RuntimeError("the transcript is empty: nothing was recognised in the recording")
    translations = await atranslate([u.text for u in units])
    async with SessionLocal() as db:
        await db.execute(delete(UnitRow).where(UnitRow.lecture_id == lecture_id))
        db.add_all(
            UnitRow(lecture_id=lecture_id, n=u.n, start=u.start, end=u.end, text_de=u.text, text_en=t)
            for u, t in zip(units, translations, strict=True)
        )
        await db.commit()


@stage
async def run_summary(lecture_id: uuid.UUID) -> None:
    """Study summary from the English translation. After this the lecture is `ready`."""
    await set_status(lecture_id, "summarizing")
    rows = await _units(lecture_id)
    async with SessionLocal() as db:
        lecture = await db.get(Lecture, lecture_id)
        assert lecture is not None
        title = lecture.title
    summary = await summary_service.summarize(title, " ".join(r.text_en or r.text_de for r in rows))
    async with SessionLocal() as db:
        await db.execute(update(Lecture).where(Lecture.id == lecture_id).values(summary=summary, status="ready", error=None))
        await db.commit()


# ---------- English re-performed lecture ----------

@stage
async def run_english_plan(lecture_id: uuid.UUID) -> None:
    """Split into topics, list what each contains, pick the lecture's German key terms."""
    await set_status(lecture_id, "chunking")
    rows = await _units(lecture_id)
    units = _as_units(rows)
    planned = await el.plan_chunks(units)

    async def checklist(c: el.PlannedChunk) -> el.Checklist:
        return await el.extract_checklist(units[c.first_unit : c.last_unit + 1])

    checklists = await _gather(checklist(c) for c in planned)
    glossary = await el.build_glossary(list(checklists))
    texts = [" ".join(u.text for u in units[c.first_unit : c.last_unit + 1]) for c in planned]
    introduce = el.introductions(glossary, texts)

    async with SessionLocal() as db:
        await db.execute(delete(Chunk).where(Chunk.lecture_id == lecture_id))  # cascades to paragraphs
        await db.execute(delete(GlossaryTerm).where(GlossaryTerm.lecture_id == lecture_id))
        db.add_all(GlossaryTerm(lecture_id=lecture_id, german=t.german, english=t.english) for t in glossary.terms)
        for c, cl, intro in zip(planned, checklists, introduce, strict=True):
            db.add(
                Chunk(
                    lecture_id=lecture_id,
                    n=c.n,
                    title=c.title,
                    first_unit=c.first_unit,
                    last_unit=c.last_unit,
                    start=units[c.first_unit].start,
                    end=units[c.last_unit].end,
                    checklist=[i.model_dump() for i in cl.items],
                    introduce=intro,
                    # Nothing worth keeping (throwaway logistics only): left out of the audio.
                    status="pending" if cl.items else "skipped",
                    verified=not cl.items,
                )
            )
        await db.commit()


@stage
async def run_english_write(lecture_id: uuid.UUID) -> None:
    """Write (and verify) every chunk that has no finished script yet."""
    await set_status(lecture_id, "scripting")
    rows = await _units(lecture_id)
    units = _as_units(rows)
    async with SessionLocal() as db:
        lecture = await db.get(Lecture, lecture_id)
        assert lecture is not None
        name = lecture.title
        chunks = list((await db.execute(select(Chunk).where(Chunk.lecture_id == lecture_id).order_by(Chunk.n))).scalars())
        snapshot = [
            dict(id=c.id, n=c.n, title=c.title, first=c.first_unit, last=c.last_unit, status=c.status,
                 checklist=el.Checklist(items=c.checklist or []), introduce=c.introduce or [])
            for c in chunks
        ]

    async def write(c: dict) -> None:
        previous = snapshot[c["n"] - 1]["title"] if c["n"] > 0 else None
        written = await el.write_chunk(
            lecture=name,
            title=c["title"],
            previous_title=previous,
            is_last=c["n"] == len(snapshot) - 1,
            checklist=c["checklist"],
            introduce=c["introduce"],
            units=units[c["first"] : c["last"] + 1],
        )
        async with SessionLocal() as db:
            await db.execute(delete(Paragraph).where(Paragraph.chunk_id == c["id"]))
            db.add_all(
                Paragraph(lecture_id=lecture_id, chunk_id=c["id"], chunk_n=c["n"], n=i, text=p.text,
                          first_unit=p.first_unit, last_unit=p.last_unit)
                for i, p in enumerate(written.paragraphs)
            )
            await db.execute(
                update(Chunk).where(Chunk.id == c["id"]).values(
                    status="done", verified=written.verified, attempts=written.attempts, verdict=written.verdict
                )
            )
            await db.commit()

    await _gather(write(c) for c in snapshot if c["status"] == "pending")
    await set_status(lecture_id, "english_ready")


async def reset_chunk(lecture_id: uuid.UUID, n: int) -> None:
    """Make one chunk be rewritten on the next english_write run."""
    async with SessionLocal() as db:
        chunk = (await db.execute(select(Chunk).where(Chunk.lecture_id == lecture_id, Chunk.n == n))).scalar_one()
        if not chunk.checklist:
            raise ValueError("this chunk was skipped: it has nothing to rewrite")
        await db.execute(delete(Paragraph).where(Paragraph.chunk_id == chunk.id))
        chunk.status, chunk.verified, chunk.attempts, chunk.verdict = "pending", False, 0, None
        await db.commit()
