import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.jobs.queue import task_queue
from app.models import Document, Lecture
from app.schemas.jobs import JobSummary

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(
    status: str | None = Query(None, description="todo | doing | succeeded | failed"),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_session),
):
    rows = (await db.execute(
        text(
            """SELECT j.id, j.task_name, j.queue_name, j.status::text AS status, j.args, j.attempts,
                      COALESCE(j.scheduled_at, now()) AS scheduled_at
               FROM procrastinate_jobs j
               WHERE (CAST(:status AS text) IS NULL OR j.status::text = CAST(:status AS text))
               ORDER BY j.id DESC LIMIT :limit"""
        ),
        {"status": status, "limit": limit},
    )).mappings().all()

    out = []
    for r in rows:
        args = r["args"] if isinstance(r["args"], dict) else json.loads(r["args"] or "{}")
        lecture_id = uuid.UUID(args["lecture_id"]) if args.get("lecture_id") else None
        document_id = uuid.UUID(args["document_id"]) if args.get("document_id") else None
        lecture = await db.get(Lecture, lecture_id) if lecture_id else None
        document = await db.get(Document, document_id) if document_id else None
        error = (lecture.error if lecture else document.error if document else None) if r["status"] == "failed" else None
        out.append(
            JobSummary(
                id=r["id"], task=r["task_name"], queue=r["queue_name"], status=r["status"],
                lecture_id=lecture_id, lecture_title=lecture.title if lecture else document.title if document else None,
                document_id=document_id, scheduled_at=r["scheduled_at"], attempts=r["attempts"], error=error,
            )
        )
    return out


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: int, db: AsyncSession = Depends(get_session)):
    """Run a failed job again with the same arguments."""
    row = (await db.execute(
        text("SELECT task_name, args, status::text AS status FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
    )).mappings().first()
    if row is None:
        raise HTTPException(404, "Job not found")
    if row["status"] != "failed":
        raise HTTPException(409, f"Only failed jobs can be retried (this one is {row['status']}).")
    args = row["args"] if isinstance(row["args"], dict) else json.loads(row["args"])
    task = task_queue.tasks[row["task_name"]]
    lock = args.get("lecture_id")
    await (task.configure(lock=lock) if lock else task).defer_async(**args)
    return {"status": "queued"}
