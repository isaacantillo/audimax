import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import ChatMessage as MessageRow
from app.models import ChatThread, Course, Document, Lecture, Passage
from app.routers.common import get_or_404
from app.schemas.chat import (
    ChatHistory,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSource,
)
from app.services import llm, retrieval

router = APIRouter(tags=["chat"])

SYSTEM = """You are a study assistant for a university course taught in German. Answer in English,
using ONLY the numbered sources. Cite them inline like [1] or [2][3]. The sources are lecture
transcripts (translated from German), an English re-telling of lectures, slides, and sometimes web
results. When a German key term matters (exams are in German), give it in German too. If the sources
do not contain the answer, say so plainly instead of guessing. Be concise and concrete."""


async def _web_sources(query: str) -> list[ChatSource]:
    if not settings.tavily_api_key:
        raise HTTPException(422, "Web search is not configured (TAVILY_API_KEY).")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
            json={"query": query, "max_results": 3},
        )
        r.raise_for_status()
    return [
        ChatSource(kind="web", ref=x["url"], snippet=x["content"][:600], title=x["title"], url=x["url"])
        for x in r.json().get("results", [])
    ]


def _source(p: Passage, titles: dict[uuid.UUID, str]) -> ChatSource:
    page = int(p.ref[1:]) if p.kind == "slides" and p.ref[1:].isdigit() else None
    return ChatSource(
        kind=p.kind,  # type: ignore[arg-type]
        ref=p.ref,
        snippet=p.text[:600],
        title=titles.get(p.lecture_id or p.document_id, ""),  # type: ignore[arg-type]
        lecture_id=p.lecture_id,
        document_id=p.document_id,
        start=p.start,
        page=page,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_session)):
    """Answer from the selected lectures/documents, with citations."""
    await get_or_404(db, Course, body.course_id, "Course")
    single = body.lecture_ids[0] if len(body.lecture_ids) == 1 and not body.document_ids else None
    only_doc = body.document_ids[0] if len(body.document_ids) == 1 and not body.lecture_ids else None

    if body.thread_id:
        thread = await get_or_404(db, ChatThread, body.thread_id, "Thread")
    else:
        thread = ChatThread(course_id=body.course_id, lecture_id=single, document_id=only_doc)
        db.add(thread)
        await db.flush()

    passages = await retrieval.search(db, body.message, lecture_ids=body.lecture_ids, document_ids=body.document_ids)
    titles: dict[uuid.UUID, str] = {}
    for p in passages:
        if p.lecture_id and p.lecture_id not in titles:
            titles[p.lecture_id] = (await db.get(Lecture, p.lecture_id)).title  # type: ignore[union-attr]
        if p.document_id and p.document_id not in titles:
            titles[p.document_id] = (await db.get(Document, p.document_id)).title  # type: ignore[union-attr]
    sources = [_source(p, titles) for p in passages]
    if body.web:
        sources += await _web_sources(body.message)

    history = (await db.execute(
        select(MessageRow).where(MessageRow.thread_id == thread.id).order_by(MessageRow.created_at.desc()).limit(8)
    )).scalars().all()[::-1]
    context = "\n\n".join(f"[{i}] ({s.kind}: {s.title}) {s.snippet}" for i, s in enumerate(sources, 1)) or "(no sources found)"
    answer = await llm.complete(
        [
            {"role": "system", "content": SYSTEM},
            *({"role": m.role, "content": m.content} for m in history),
            {"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {body.message}"},
        ]
    )

    db.add(MessageRow(thread_id=thread.id, role="user", content=body.message, sources=[]))
    db.add(MessageRow(thread_id=thread.id, role="assistant", content=answer, sources=[s.model_dump(mode="json") for s in sources]))
    await db.commit()
    return ChatResponse(thread_id=thread.id, message=ChatMessage(role="assistant", content=answer, sources=sources))


@router.get("/chat/history", response_model=ChatHistory)
async def history(
    course_id: uuid.UUID,
    lecture_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_session),
):
    """The latest conversation for this screen (a lecture's chat, a document's, or the course's)."""
    stmt = select(ChatThread).where(
        ChatThread.course_id == course_id,
        ChatThread.lecture_id == lecture_id if lecture_id else ChatThread.lecture_id.is_(None),
        ChatThread.document_id == document_id if document_id else ChatThread.document_id.is_(None),
    ).order_by(ChatThread.created_at.desc()).limit(1)
    thread = (await db.execute(stmt)).scalar_one_or_none()
    if thread is None:
        return ChatHistory(thread_id=None, messages=[])
    rows = (await db.execute(select(MessageRow).where(MessageRow.thread_id == thread.id).order_by(MessageRow.created_at))).scalars()
    return ChatHistory(
        thread_id=thread.id,
        messages=[ChatMessage(role=m.role, content=m.content, sources=[ChatSource.model_validate(x) for x in m.sources]) for m in rows],  # type: ignore[arg-type]
    )
