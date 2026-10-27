"""Queue tasks: each runs one pipeline stage and defers the next one.

Tasks of the same lecture share a `lock`, so they run one at a time (a chunk rerun can't overlap
the original run)."""

import uuid

import procrastinate

from app.jobs import pipeline as p
from app.jobs.queue import task_queue

RETRY = procrastinate.RetryStrategy(max_attempts=2, wait=30)


async def defer(task, lecture_id: str, **kwargs) -> None:
    await task.configure(lock=lecture_id).defer_async(lecture_id=lecture_id, **kwargs)


# The English version is only made on request (POST /lectures/{id}/english), never as part of an upload.
# `**_` accepts the `english=` argument that jobs queued before that change still carry, so they can retry.


@task_queue.task(name="transcribe_lecture", queue="transcribe", retry=RETRY)
async def transcribe_lecture(lecture_id: str, **_: object) -> None:
    await p.run_transcribe(uuid.UUID(lecture_id))
    await defer(translate_lecture, lecture_id)


@task_queue.task(name="translate_lecture", queue="llm", retry=RETRY)
async def translate_lecture(lecture_id: str, **_: object) -> None:
    await p.run_translate(uuid.UUID(lecture_id))
    await defer(summarize_lecture, lecture_id)


@task_queue.task(name="summarize_lecture", queue="llm", retry=RETRY)
async def summarize_lecture(lecture_id: str, **_: object) -> None:
    await p.run_summary(uuid.UUID(lecture_id))


@task_queue.task(name="english_plan", queue="llm", retry=RETRY)
async def english_plan(lecture_id: str) -> None:
    await p.run_english_plan(uuid.UUID(lecture_id))
    await defer(english_write, lecture_id)


@task_queue.task(name="english_write", queue="llm", retry=RETRY)
async def english_write(lecture_id: str) -> None:
    await p.run_english_write(uuid.UUID(lecture_id))
