import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from app.auth import current_user, hash_password
from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.routers import auth, dummy

log = logging.getLogger("audimax")



def operation_id(route: APIRoute) -> str:
    """Route function name -> clean generated client names (listCourses, not listCoursesApiCoursesGet)."""
    return route.name


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create the single user on first start. Migrations run in the `migrate` service."""
    async with SessionLocal() as db:
        if await db.scalar(select(func.count()).select_from(User)) == 0:
            if settings.admin_password:
                db.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
                await db.commit()
                log.warning("created user %r", settings.admin_username)
            else:
                log.warning("no users exist and ADMIN_PASSWORD is not set: nobody can log in")
    yield


app = FastAPI(title="Audimax", generate_unique_id_function=operation_id, lifespan=lifespan)

api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(auth.router)
# Everything except /health and /auth/login requires a session cookie or bearer token.
api.include_router(dummy.router, dependencies=[Depends(current_user)])
app.include_router(api)

# Low priority: every /api route above is matched first; anything else is served from the
# built SPA, falling back to index.html so client-side routes survive a refresh.
# check_dir="auto": missing dist/ only warns under `fastapi dev`, errors under `fastapi run`.
app.frontend("/", directory=Path(__file__).parent.parent / "dist")
