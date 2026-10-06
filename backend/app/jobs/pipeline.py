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
from app.config import settings
from app.db import SessionLocal
from app.models import (
    Chunk,
    Document,
    DocumentSection,
    GlossaryTerm,
    Lecture,
    LecturePart,
    Paragraph,
)
from app.models import (
    Unit as UnitRow,
)
from app.services import documents as documents_service
from app.services import english_lecture as el
from app.services import insights, llm, retrieval
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


# ---------- original lecture: transcribe -> translate -> index ----------

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
async def run_index(lecture_id: uuid.UUID) -> None:
    """Summary + searchable transcript. After this the lecture is `ready`."""
    await set_status(lecture_id, "indexing")
    rows = await _units(lecture_id)
    async with SessionLocal() as db:
        lecture = await db.get(Lecture, lecture_id)
        assert lecture is not None
        title, course_id = lecture.title, lecture.course_id

    english = " ".join(r.text_en or r.text_de for r in rows)
    summary = await insights.summarize(title, english)
    items = retrieval.windows([(r.n, r.start, r.text_en or r.text_de) for r in rows])
    vectors = await llm.embed([i.text for i in items])

    async with SessionLocal() as db:
        await retrieval.replace_passages(
            db, course_id=course_id, lecture_id=lecture_id, kind="transcript", items=items, vectors=vectors
        )
        from app.models import Course

        await db.execute(update(Lecture).where(Lecture.id == lecture_id).values(summary=summary, mindmap=None, status="ready", error=None))
        await db.execute(update(Course).where(Course.id == course_id).values(mindmap=None))
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


@stage
async def run_english_voice(lecture_id: uuid.UUID) -> None:
    """One TTS clip per paragraph. The provider is pinned per lecture: if it fails, the whole
    lecture is re-voiced with the next one, so the voice never changes mid-lecture."""
    await set_status(lecture_id, "voicing")
    async with SessionLocal() as db:
        lecture = await db.get(Lecture, lecture_id)
        assert lecture is not None
        pinned = lecture.tts_provider
    providers = settings.tts_provider_list
    ordered = [p for p in providers if p[0] == pinned] + [p for p in providers if p[0] != pinned]

    last_error: Exception | None = None
    for name, model, voice in ordered:
        async with SessionLocal() as db:
            current = (await db.get(Lecture, lecture_id)).tts_provider  # type: ignore[union-attr]
            if current not in (None, name):
                await db.execute(update(Paragraph).where(Paragraph.lecture_id == lecture_id).values(clip_key=None))
            await db.execute(update(Lecture).where(Lecture.id == lecture_id).values(tts_provider=name))
            await db.commit()
            paragraphs = list((await db.execute(
                select(Paragraph).where(Paragraph.lecture_id == lecture_id).order_by(Paragraph.chunk_n, Paragraph.n)
            )).scalars())
            todo = [(p.id, p.text) for p in paragraphs]

        async def voice_one(pid: uuid.UUID, text: str, model=model, voice=voice) -> None:
            key = el.clip_key(lecture_id, model, voice, text)
            # Clips are content-addressed: an unchanged paragraph is never paid for twice.
            if not await asyncio.to_thread(storage.exists, key):
                wav = await llm.speak(model, voice, text)
                await asyncio.to_thread(storage.put_bytes, key, wav, "audio/wav")
            async with SessionLocal() as db:
                await db.execute(update(Paragraph).where(Paragraph.id == pid).values(clip_key=key))
                await db.commit()

        try:
            await _gather(voice_one(pid, text) for pid, text in todo)
        except Exception as exc:  # noqa: BLE001 - any provider failure means "try the next voice"
            log.warning("TTS provider %s failed (%s); re-voicing the whole lecture with the next one", name, exc)
            last_error = exc
            continue
        return
    raise RuntimeError(f"all TTS providers failed: {last_error}")


@stage
async def run_english_assemble(lecture_id: uuid.UUID) -> None:
    await set_status(lecture_id, "assembling")
    async with SessionLocal() as db:
        paragraphs = list((await db.execute(
            select(Paragraph).where(Paragraph.lecture_id == lecture_id).order_by(Paragraph.chunk_n, Paragraph.n)
        )).scalars())
    if not paragraphs or any(p.clip_key is None for p in paragraphs):
        raise RuntimeError("some paragraphs have no audio yet")

    grouped: dict[int, list[Paragraph]] = {}
    for p in paragraphs:
        grouped.setdefault(p.chunk_n, []).append(p)

    with tempfile.TemporaryDirectory() as tmp:
        clip_paths: dict[str, Path] = {}
        for p in paragraphs:
            assert p.clip_key
            dest = Path(tmp) / Path(p.clip_key).name
            if p.clip_key not in clip_paths:
                await asyncio.to_thread(storage.get_to_path, p.clip_key, dest)
                clip_paths[p.clip_key] = dest
        out = Path(tmp) / "english.mp3"
        order = sorted(grouped)
        timings, total = await el.astitch([[clip_paths[p.clip_key] for p in grouped[n]] for n in order], out)  # type: ignore[index]
        key = f"lectures/{lecture_id}/english.mp3"
        await asyncio.to_thread(storage.put_file, key, out, "audio/mpeg")

    async with SessionLocal() as db:
        for n, row in zip(order, timings, strict=True):
            for p, (start, end) in zip(grouped[n], row, strict=True):
                await db.execute(update(Paragraph).where(Paragraph.id == p.id).values(start=start, end=end))
        await db.execute(
            update(Lecture).where(Lecture.id == lecture_id).values(
                english_audio_key=key, english_duration=total, status="english_ready", error=None
            )
        )
        await db.commit()


@stage
async def run_english_index(lecture_id: uuid.UUID) -> None:
    """Make the English script citable by chat."""
    async with SessionLocal() as db:
        lecture = await db.get(Lecture, lecture_id)
        assert lecture is not None
        course_id = lecture.course_id
        paragraphs = list((await db.execute(
            select(Paragraph).where(Paragraph.lecture_id == lecture_id).order_by(Paragraph.chunk_n, Paragraph.n)
        )).scalars())
    items = [retrieval.Item(f"{p.chunk_n:02d}.{p.n:02d}", p.start, p.text) for p in paragraphs]
    vectors = await llm.embed([i.text for i in items])
    async with SessionLocal() as db:
        await retrieval.replace_passages(db, course_id=course_id, lecture_id=lecture_id, kind="english", items=items, vectors=vectors)
        await db.commit()


async def reset_chunk(lecture_id: uuid.UUID, n: int) -> None:
    """Make one chunk be rewritten (and re-voiced) on the next english_write run."""
    async with SessionLocal() as db:
        chunk = (await db.execute(select(Chunk).where(Chunk.lecture_id == lecture_id, Chunk.n == n))).scalar_one()
        if not chunk.checklist:
            raise ValueError("this chunk was skipped: it has nothing to rewrite")
        await db.execute(delete(Paragraph).where(Paragraph.chunk_id == chunk.id))
        chunk.status, chunk.verified, chunk.attempts, chunk.verdict = "pending", False, 0, None
        await db.commit()


# ---------- slides / scriptum ----------

async def run_document(document_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        assert doc is not None
        doc.status, doc.error = "processing", None
        await db.commit()
        key, filename, course_id = doc.file_key, doc.filename, doc.course_id
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / filename
            await asyncio.to_thread(storage.get_to_path, key, path)
            page_count, sections = await asyncio.to_thread(documents_service.parse_pdf, path)
        if not sections:
            raise RuntimeError("no text found in the PDF (scanned pages are not supported yet)")
        items = [
            retrieval.Item(f"p{s.page}", None, piece)
            for s in sections
            for piece in retrieval.split_text(s.text)
        ]
        vectors = await llm.embed([i.text for i in items])
        async with SessionLocal() as db:
            await db.execute(delete(DocumentSection).where(DocumentSection.document_id == document_id))
            db.add_all(DocumentSection(document_id=document_id, n=i, page=s.page, heading=s.heading, text=s.text) for i, s in enumerate(sections))
            await retrieval.replace_passages(db, course_id=course_id, document_id=document_id, kind="slides", items=items, vectors=vectors)
            await db.execute(update(Document).where(Document.id == document_id).values(status="ready", page_count=page_count, error=None))
            await db.commit()
    except Exception as exc:
        log.exception("document %s failed", document_id)
        async with SessionLocal() as db:
            await db.execute(update(Document).where(Document.id == document_id).values(status="failed", error=str(exc)[:1000]))
            await db.commit()
        raise
