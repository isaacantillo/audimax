from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from app.routers import dummy



def operation_id(route: APIRoute) -> str:
    """Route function name -> clean generated client names (listCourses, not listCoursesApiCoursesGet)."""
    return route.name


app = FastAPI(title="Audimax", generate_unique_id_function=operation_id)

api = APIRouter(prefix="/api")


@api.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(dummy.router)
app.include_router(api)

# Low priority: every /api route above is matched first; anything else is served from the
# built SPA, falling back to index.html so client-side routes survive a refresh.
# check_dir="auto": missing dist/ only warns under `fastapi dev`, errors under `fastapi run`.
app.frontend("/", directory=Path(__file__).parent.parent / "dist")
