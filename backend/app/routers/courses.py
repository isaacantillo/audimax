import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.auth import current_user
from app.db import get_session
from app.models import Chunk, Course, Lecture, User
from app.routers.common import owned_course
from app.schemas.courses import CourseCreate, CourseSummary
from app.schemas.enums import IDLE_STATUSES, LectureStatus
from app.schemas.lectures import LectureSummary

router = APIRouter(tags=["courses"])
_IDLE = {s.value for s in IDLE_STATUSES}


async def _summary(db: AsyncSession, course: Course) -> CourseSummary:
    lectures = list((await db.execute(select(Lecture).where(Lecture.course_id == course.id))).scalars())
    return CourseSummary(
        id=course.id,
        name=course.name,
        added_by=await db.scalar(select(User.username).where(User.id == course.user_id)) or "",
        lecture_count=len(lectures),
        last_activity_at=max([course.created_at, *(l.updated_at for l in lectures)]),
        has_active_jobs=any(l.status not in _IDLE for l in lectures),
    )


@router.get("/courses", response_model=list[CourseSummary])
async def list_courses(user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    query = select(Course).order_by(Course.created_at)
    if not user.is_admin:
        query = query.where(Course.user_id == user.id)
    courses = (await db.execute(query)).scalars()
    return [await _summary(db, c) for c in courses]


@router.post("/courses", response_model=CourseSummary, status_code=201)
async def create_course(body: CourseCreate, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    course = Course(user_id=user.id, name=body.name.strip() or "Untitled course")
    db.add(course)
    await db.commit()
    return await _summary(db, course)


@router.get("/courses/{course_id}", response_model=CourseSummary)
async def get_course(course_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    return await _summary(db, await owned_course(db, course_id, user))


@router.delete("/courses/{course_id}", status_code=204)
async def delete_course(course_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    course = await owned_course(db, course_id, user)
    ids = (await db.execute(select(Lecture.id).where(Lecture.course_id == course_id))).scalars().all()
    await db.delete(course)
    await db.commit()
    for lecture_id in ids:
        storage.delete_prefix(f"lectures/{lecture_id}/")


@router.get("/courses/{course_id}/lectures", response_model=list[LectureSummary])
async def list_lectures(course_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    await owned_course(db, course_id, user)
    lectures = (await db.execute(
        select(Lecture).where(Lecture.course_id == course_id).order_by(Lecture.date, Lecture.created_at)
    )).scalars()
    lectures = list(lectures)
    with_english = set((await db.execute(
        select(Chunk.lecture_id).where(Chunk.lecture_id.in_([l.id for l in lectures]), Chunk.status == "done").distinct()
    )).scalars())
    return [
        LectureSummary(
            id=l.id,
            title=l.title,
            summary=l.summary or "",
            status=LectureStatus(l.status),
            duration_seconds=int(l.duration),
            date=l.date,
            has_english=l.id in with_english,
        )
        for l in lectures
    ]
