"""Embedding + similarity search over lecture transcripts, English scripts and slides."""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Passage
from app.services import llm

WINDOW_CHARS = 900


@dataclass
class Item:
    ref: str
    start: float | None
    text: str


def windows(units: list[tuple[int, float, str]]) -> list[Item]:
    """Group consecutive sentences (n, start, text) into ~900 character passages."""
    out: list[Item] = []
    buf: list[str] = []
    first = last = 0
    start = 0.0
    size = 0
    for n, s, text in units:
        if not buf:
            first, start = n, s
        buf.append(text)
        last = n
        size += len(text) + 1
        if size >= WINDOW_CHARS:
            out.append(Item(f"{first}-{last}", start, " ".join(buf)))
            buf, size = [], 0
    if buf:
        out.append(Item(f"{first}-{last}", start, " ".join(buf)))
    return out


def split_text(text: str, limit: int = 1200) -> list[str]:
    """Split on blank lines, packing paragraphs up to `limit` characters."""
    parts: list[str] = []
    buf = ""
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        if buf and len(buf) + len(para) > limit:
            parts.append(buf)
            buf = ""
        buf = f"{buf}\n\n{para}".strip()
        while len(buf) > limit * 1.5:
            parts.append(buf[:limit])
            buf = buf[limit:]
    if buf:
        parts.append(buf)
    return parts


async def replace_passages(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    kind: str,
    items: list[Item],
    vectors: list[list[float]],
    lecture_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
) -> None:
    """Swap all passages of one (owner, kind) for fresh ones. Embedding happens before the call."""
    stmt = delete(Passage).where(Passage.kind == kind)
    stmt = stmt.where(Passage.lecture_id == lecture_id) if lecture_id else stmt.where(Passage.document_id == document_id)
    await db.execute(stmt)
    db.add_all(
        Passage(
            course_id=course_id,
            lecture_id=lecture_id,
            document_id=document_id,
            kind=kind,
            ref=item.ref,
            start=item.start,
            text=item.text,
            embedding=vector,
        )
        for item, vector in zip(items, vectors, strict=True)
    )


async def search(
    db: AsyncSession,
    query: str,
    *,
    lecture_ids: list[uuid.UUID],
    document_ids: list[uuid.UUID],
    k: int = 8,
) -> list[Passage]:
    if not lecture_ids and not document_ids:
        return []
    [vector] = await llm.embed([query])
    stmt = (
        select(Passage)
        .where((Passage.lecture_id.in_(lecture_ids)) | (Passage.document_id.in_(document_ids)))
        .order_by(Passage.embedding.cosine_distance(vector))
        .limit(k)
    )
    return list((await db.execute(stmt)).scalars())
