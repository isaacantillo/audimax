import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_session
from app.jobs.queue import task_queue
from app.models import User
from app.routers.common import owned_lecture
from app.schemas.jobs import JobSummary

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(
    status: str | None = Query(None, description="todo | doing | succeeded | failed"),
    limit: int = Query(100, le=500),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
):
    # A job belongs to the owner of its lecture's course; jobs of deleted lectures are admin-only.
    rows = (await db.execute(
        text(
            """SELECT j.id, j.task_name, j.queue_name, j.status::text AS status, j.args, j.attempts,
                      COALESCE(j.scheduled_at, now()) AS scheduled_at,
                      l.id AS lecture_id, l.title AS lecture_title, l.error AS lecture_error
               FROM procrastinate_jobs j
               LEFT JOIN lectures l ON l.id::text = j.args->>'lecture_id'
               LEFT JOIN courses c ON c.id = l.course_id
               WHERE (CAST(:status AS text) IS NULL OR j.status::text = CAST(:status AS text))
                 AND (:admin OR c.user_id = :user_id)
               ORDER BY j.id DESC LIMIT :limit"""
        ),
        {"status": status, "limit": limit, "admin": user.is_admin, "user_id": user.id},
    )).mappings().all()

    out = []
    for r in rows:
        args = r["args"] if isinstance(r["args"], dict) else json.loads(r["args"] or "{}")
        lecture_id = uuid.UUID(args["lecture_id"]) if args.get("lecture_id") else None
        error = r["lecture_error"] if r["status"] == "failed" else None
        out.append(
            JobSummary(
                id=r["id"], task=r["task_name"], queue=r["queue_name"], status=r["status"],
                lecture_id=lecture_id, lecture_title=r["lecture_title"],
                scheduled_at=r["scheduled_at"], attempts=r["attempts"], error=error,
            )
        )
    return out


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)):
    """Run a failed job again with the same arguments."""
    row = (await db.execute(
        text("SELECT task_name, args, status::text AS status FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
    )).mappings().first()
    if row is None:
        raise HTTPException(404, "Job not found")
    if row["status"] != "failed":
        raise HTTPException(409, f"Only failed jobs can be retried (this one is {row['status']}).")
    args = row["args"] if isinstance(row["args"], dict) else json.loads(row["args"])
    if args.get("lecture_id"):
        await owned_lecture(db, uuid.UUID(args["lecture_id"]), user)
    elif not user.is_admin:
        raise HTTPException(404, "Job not found")
    task = task_queue.tasks[row["task_name"]]
    lock = args.get("lecture_id")
    await (task.configure(lock=lock) if lock else task).defer_async(**args)
    return {"status": "queued"}
