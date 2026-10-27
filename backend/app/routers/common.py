import uuid
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Lecture, User

T = TypeVar("T")


def media_url(key: str) -> str:
    """Same-origin URL: the browser sends its session cookie, then gets redirected to R2."""
    return f"/api/media/{key}"


async def get_or_404(db: AsyncSession, model: type[T], id: uuid.UUID, what: str | None = None) -> T:
    obj = await db.get(model, id)
    if obj is None:
        raise HTTPException(404, f"{what or model.__name__} not found")
    return obj


# Someone else's course or lecture is a 404, exactly like a missing one: its existence is not revealed.
# Admins own everything.


def can_see(user: User, course: Course) -> bool:
    return user.is_admin or course.user_id == user.id


async def owned_course(db: AsyncSession, course_id: uuid.UUID, user: User) -> Course:
    course = await db.get(Course, course_id)
    if course is None or not can_see(user, course):
        raise HTTPException(404, "Course not found")
    return course


async def owned_lecture(db: AsyncSession, lecture_id: uuid.UUID, user: User) -> Lecture:
    row = (await db.execute(select(Lecture, Course).join(Course, Course.id == Lecture.course_id).where(Lecture.id == lecture_id))).first()
    if row is None or not can_see(user, row.Course):
        raise HTTPException(404, "Lecture not found")
    return row.Lecture
