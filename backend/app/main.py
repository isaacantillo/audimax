import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from app.auth import current_user, hash_password
from app.config import settings
from app.db import SessionLocal
from app.jobs.queue import task_queue
from app.models import User
from app.routers import auth, courses, jobs, lectures, live, media, search

log = logging.getLogger("audimax")


def operation_id(route: APIRoute) -> str:
    """Route function name -> clean generated client names (listCourses, not listCoursesApiCoursesGet)."""
    return route.name


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Open the job queue (the app only enqueues; the worker service runs the jobs) and create the
    single user on first start. Migrations run in the `migrate` service."""
    async with SessionLocal() as db:
        if await db.scalar(select(func.count()).select_from(User)) == 0:
            if settings.admin_password:
                db.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
                await db.commit()
                log.warning("created user %r", settings.admin_username)
            else:
                log.warning("no users exist and ADMIN_PASSWORD is not set: nobody can log in")
    async with task_queue.open_async():
        yield


app = FastAPI(title="Audimax", generate_unique_id_function=operation_id, lifespan=lifespan)

api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(auth.router)
# Everything except /health and /auth/login requires a session cookie or bearer token.
for router in (courses, lectures, jobs, search, media):
    api.include_router(router.router, dependencies=[Depends(current_user)])
api.include_router(live.router)
app.include_router(api)
