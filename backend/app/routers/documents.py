import re
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.db import get_session
from app.jobs import tasks
from app.models import Course, Document, DocumentSection, Lecture
from app.routers.common import get_or_404, media_url
from app.schemas import documents as s
from app.schemas.courses import Course as CourseRef
from app.schemas.enums import FileProcessingStatus
from app.schemas.lectures import Lecture as LectureRef

router = APIRouter(tags=["documents"])


async def _summary(db: AsyncSession, d: Document) -> s.DocumentSummary:
    course = await db.get(Course, d.course_id)
    lecture = await db.get(Lecture, d.lecture_id) if d.lecture_id else None
    return s.DocumentSummary(
        id=d.id,
        title=d.title,
        type="slides",
        status=FileProcessingStatus(d.status),
        course=CourseRef(id=course.id, name=course.name),  # type: ignore[union-attr]
        lecture=LectureRef(id=lecture.id, title=lecture.title) if lecture else None,
    )


@router.post("/documents", response_model=s.DocumentSummary, status_code=201)
async def create_document(
    course_id: uuid.UUID = Form(),
    lecture_id: uuid.UUID | None = Form(None),
    title: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
):
    """Upload slides or a scriptum (PDF). Parsed and made searchable in the background."""
    await get_or_404(db, Course, course_id, "Course")
    if lecture_id:
        lecture = await get_or_404(db, Lecture, lecture_id, "Lecture")
        if lecture.course_id != course_id:
            raise HTTPException(422, "That lecture belongs to another course.")
    filename = file.filename or "document.pdf"
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(422, "Only PDF files are supported.")

    doc = Document(
        course_id=course_id, lecture_id=lecture_id, title=title.strip() or Path(filename).stem,
        filename=re.sub(r"[^A-Za-z0-9._-]+", "_", filename), file_key="",
    )
    db.add(doc)
    await db.flush()
    doc.file_key = f"documents/{doc.id}/{doc.filename}"
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)
        tmp.flush()
        storage.put_file(doc.file_key, Path(tmp.name), "application/pdf")
    await db.commit()
    await tasks.process_document.defer_async(document_id=str(doc.id))
    return await _summary(db, doc)


@router.get("/documents/{document_id}", response_model=s.DocumentDetails)
async def get_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    d = await get_or_404(db, Document, document_id, "Document")
    sections = (await db.execute(select(DocumentSection).where(DocumentSection.document_id == document_id).order_by(DocumentSection.n))).scalars()
    return s.DocumentDetails(
        **(await _summary(db, d)).model_dump(),
        file_url=media_url(d.file_key),
        page_count=d.page_count,
        error=d.error,
        sections=[s.DocumentSection(page=x.page, heading=x.heading, text=x.text) for x in sections],
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    d = await get_or_404(db, Document, document_id, "Document")
    await db.delete(d)
    await db.commit()
    storage.delete_prefix(f"documents/{document_id}/")
