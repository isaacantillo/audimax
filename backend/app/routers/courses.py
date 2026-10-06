import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Course, Document, Lecture
from app.routers.common import get_or_404
from app.schemas.chat import ChatSelection
from app.schemas.courses import Course as CourseRef
from app.schemas.courses import CourseCreate, CourseSummary
from app.schemas.documents import DocumentSummary
from app.schemas.enums import IDLE_STATUSES, FileProcessingStatus, LectureStatus
from app.schemas.lectures import Lecture as LectureRef
from app.schemas.lectures import LectureSummary
from app.schemas.mindmap import MindMapResponse
from app.services import insights

router = APIRouter(tags=["courses"])
_IDLE = {s.value for s in IDLE_STATUSES}


async def _summary(db: AsyncSession, course: Course) -> CourseSummary:
    lectures = list((await db.execute(select(Lecture).where(Lecture.course_id == course.id))).scalars())
    documents = list((await db.execute(select(Document).where(Document.course_id == course.id))).scalars())
    times = [course.created_at, *(l.updated_at for l in lectures), *(d.created_at for d in documents)]
    return CourseSummary(
        id=course.id,
        name=course.name,
        lecture_count=len(lectures),
        document_count=len(documents),
        last_activity_at=max(times),
        has_active_jobs=any(l.status not in _IDLE for l in lectures)
        or any(d.status in ("queued", "processing") for d in documents),
    )


@router.get("/courses", response_model=list[CourseSummary])
async def list_courses(db: AsyncSession = Depends(get_session)):
    courses = (await db.execute(select(Course).order_by(Course.created_at))).scalars()
    return [await _summary(db, c) for c in courses]


@router.post("/courses", response_model=CourseSummary, status_code=201)
async def create_course(body: CourseCreate, db: AsyncSession = Depends(get_session)):
    course = Course(name=body.name.strip() or "Untitled course")
    db.add(course)
    await db.commit()
    return await _summary(db, course)


@router.get("/courses/{course_id}", response_model=CourseSummary)
async def get_course(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    return await _summary(db, await get_or_404(db, Course, course_id, "Course"))


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    from app import storage

    course = await get_or_404(db, Course, course_id, "Course")
    ids = (await db.execute(select(Lecture.id).where(Lecture.course_id == course_id))).scalars().all()
    doc_ids = (await db.execute(select(Document.id).where(Document.course_id == course_id))).scalars().all()
    await db.delete(course)
    await db.commit()
    for lecture_id in ids:
        storage.delete_prefix(f"lectures/{lecture_id}/")
    for doc_id in doc_ids:
        storage.delete_prefix(f"documents/{doc_id}/")


@router.get("/courses/{course_id}/lectures", response_model=list[LectureSummary])
async def list_lectures(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    await get_or_404(db, Course, course_id, "Course")
    lectures = (await db.execute(select(Lecture).where(Lecture.course_id == course_id).order_by(Lecture.date, Lecture.created_at))).scalars()
    doc_counts = dict((await db.execute(
        select(Document.lecture_id, func.count()).where(Document.course_id == course_id, Document.lecture_id.is_not(None)).group_by(Document.lecture_id)
    )).all())
    return [
        LectureSummary(
            id=l.id,
            title=l.title,
            document_count=doc_counts.get(l.id, 0),
            summary=l.summary or "",
            status=LectureStatus(l.status),
            duration_seconds=int(l.duration),
            date=l.date,
            has_english=l.english_audio_key is not None,
        )
        for l in lectures
    ]


@router.get("/courses/{course_id}/documents", response_model=list[DocumentSummary])
async def list_documents(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    course = await get_or_404(db, Course, course_id, "Course")
    docs = (await db.execute(select(Document).where(Document.course_id == course_id).order_by(Document.created_at))).scalars()
    out = []
    for d in docs:
        lecture = await db.get(Lecture, d.lecture_id) if d.lecture_id else None
        out.append(
            DocumentSummary(
                id=d.id,
                title=d.title,
                type="slides",
                status=FileProcessingStatus(d.status),
                course=CourseRef(id=course.id, name=course.name),
                lecture=LectureRef(id=lecture.id, title=lecture.title) if lecture else None,
            )
        )
    return out


@router.get("/courses/{course_id}/chat-selection", response_model=ChatSelection)
async def get_chat_selection(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    course = await get_or_404(db, Course, course_id, "Course")
    return ChatSelection.model_validate(course.chat_selection or {})


@router.put("/courses/{course_id}/chat-selection", response_model=ChatSelection)
async def set_chat_selection(course_id: uuid.UUID, body: ChatSelection, db: AsyncSession = Depends(get_session)):
    course = await get_or_404(db, Course, course_id, "Course")
    course.chat_selection = body.model_dump(mode="json")
    await db.commit()
    return body


async def _build_course_mindmap(db: AsyncSession, course: Course) -> dict:
    lectures = (await db.execute(
        select(Lecture).where(Lecture.course_id == course.id, Lecture.summary.is_not(None)).order_by(Lecture.date, Lecture.created_at)
    )).scalars().all()
    if not lectures:
        return {"nodes": [], "edges": []}
    return await insights.course_mindmap(course.name, [(l.title, l.summary or "") for l in lectures])


@router.get("/courses/{course_id}/mindmap", response_model=MindMapResponse)
async def course_mindmap(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """Always all lectures. Generated on first request and cached until a lecture changes."""
    course = await get_or_404(db, Course, course_id, "Course")
    if course.mindmap is None:
        course.mindmap = await _build_course_mindmap(db, course)
        await db.commit()
    return course.mindmap


@router.post("/courses/{course_id}/mindmap/refresh", response_model=MindMapResponse)
async def refresh_course_mindmap(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    course = await get_or_404(db, Course, course_id, "Course")
    course.mindmap = await _build_course_mindmap(db, course)
    await db.commit()
    return course.mindmap
