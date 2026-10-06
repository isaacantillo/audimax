import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Lecture, Paragraph, Unit
from app.schemas.search import SearchHit, SearchResponse

router = APIRouter(tags=["search"])


def _like(query: str) -> str:
    """Escape LIKE wildcards so the user's text is matched literally."""
    return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(min_length=2, max_length=200),
    course_id: uuid.UUID | None = None,
    limit: int = Query(40, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    """Find a word or phrase in the German transcripts, their translations and the English scripts.

    Plain case-insensitive substring match: no AI, no cost, finds "Vererbung" inside "Mehrfachvererbung"."""
    pattern = _like(q.strip())
    order = (Lecture.date, Lecture.created_at, Lecture.id)

    units = (
        select(Unit, Lecture)
        .join(Lecture, Lecture.id == Unit.lecture_id)
        .where(Unit.text_de.ilike(pattern, escape="\\") | Unit.text_en.ilike(pattern, escape="\\"))
        .order_by(*order, Unit.n)
        .limit(limit + 1)
    )
    paragraphs = (
        select(Paragraph, Lecture)
        .join(Lecture, Lecture.id == Paragraph.lecture_id)
        .where(Paragraph.text.ilike(pattern, escape="\\"), Paragraph.start.is_not(None))
        .order_by(*order, Paragraph.chunk_n, Paragraph.n)
        .limit(limit + 1)
    )
    if course_id:
        units = units.where(Lecture.course_id == course_id)
        paragraphs = paragraphs.where(Lecture.course_id == course_id)

    unit_rows = (await db.execute(units)).all()
    paragraph_rows = (await db.execute(paragraphs)).all()
    truncated = len(unit_rows) > limit or len(paragraph_rows) > limit

    hits = [
        SearchHit(
            lecture_id=lecture.id, lecture_title=lecture.title, course_id=lecture.course_id, kind="transcript",
            start=unit.start, text=unit.text_de, text_translated=unit.text_en,
        )
        for unit, lecture in unit_rows[:limit]
    ] + [
        SearchHit(
            lecture_id=lecture.id, lecture_title=lecture.title, course_id=lecture.course_id, kind="english",
            start=paragraph.start or 0.0, text=paragraph.text, text_translated=None,
        )
        for paragraph, lecture in paragraph_rows[:limit]
    ]
    return SearchResponse(query=q.strip(), hits=hits, truncated=truncated)
