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


@task_queue.task(name="transcribe_lecture", queue="transcribe", retry=RETRY)
async def transcribe_lecture(lecture_id: str, english: bool = False) -> None:
    await p.run_transcribe(uuid.UUID(lecture_id))
    await defer(translate_lecture, lecture_id, english=english)


@task_queue.task(name="translate_lecture", queue="llm", retry=RETRY)
async def translate_lecture(lecture_id: str, english: bool = False) -> None:
    await p.run_translate(uuid.UUID(lecture_id))
    await defer(index_lecture, lecture_id, english=english)


@task_queue.task(name="index_lecture", queue="llm", retry=RETRY)
async def index_lecture(lecture_id: str, english: bool = False) -> None:
    await p.run_index(uuid.UUID(lecture_id))
    if english:
        await defer(english_plan, lecture_id)


@task_queue.task(name="english_plan", queue="llm", retry=RETRY)
async def english_plan(lecture_id: str) -> None:
    await p.run_english_plan(uuid.UUID(lecture_id))
    await defer(english_write, lecture_id)


@task_queue.task(name="english_write", queue="llm", retry=RETRY)
async def english_write(lecture_id: str) -> None:
    await p.run_english_write(uuid.UUID(lecture_id))
    await defer(english_voice, lecture_id)


@task_queue.task(name="english_voice", queue="tts", retry=RETRY)
async def english_voice(lecture_id: str) -> None:
    await p.run_english_voice(uuid.UUID(lecture_id))
    await defer(english_assemble, lecture_id)


@task_queue.task(name="english_assemble", queue="media", retry=RETRY)
async def english_assemble(lecture_id: str) -> None:
    await p.run_english_assemble(uuid.UUID(lecture_id))
    await defer(english_index, lecture_id)


@task_queue.task(name="english_index", queue="llm", retry=RETRY)
async def english_index(lecture_id: str) -> None:
    await p.run_english_index(uuid.UUID(lecture_id))


@task_queue.task(name="process_document", queue="llm", retry=RETRY)
async def process_document(document_id: str) -> None:
    await p.run_document(uuid.UUID(document_id))
