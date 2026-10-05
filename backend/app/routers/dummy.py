"""Hard-coded data matching the response schemas. Replaced router by router in Phase 3."""

import datetime
import uuid

from fastapi import APIRouter, HTTPException

from app.schemas.courses import CourseSummary
from app.schemas.enums import FileProcessingStatus
from app.schemas.lectures import LectureSummary, TranscriptDetails, TranscriptSegment
from app.schemas.mindmap import MindMapEdge, MindMapNode, MindMapResponse

router = APIRouter()

COURSE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LECTURE_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")


@router.get("/courses", response_model=list[CourseSummary], tags=["courses"])
def list_courses():
    return [
        CourseSummary(
            id=COURSE_ID,
            name="Software Engineering 1",
            lecture_count=1,
            document_count=0,
            last_activity_at=datetime.datetime(2026, 10, 5, 12, 0),
            has_active_jobs=False,
        )
    ]


@router.get("/courses/{course_id}/lectures", response_model=list[LectureSummary], tags=["courses"])
def list_lectures(course_id: uuid.UUID):
    return [
        LectureSummary(
            id=LECTURE_ID,
            title="SE1 L1: Organisation and why software engineering",
            document_count=0,
            summary="Course organisation, grading, and why software engineering matters.",
        )
    ]


@router.get("/lectures/{lecture_id}", response_model=TranscriptDetails, tags=["lectures"])
def get_lecture(lecture_id: uuid.UUID):
    if lecture_id != LECTURE_ID:
        raise HTTPException(404, "Lecture not found")
    return TranscriptDetails(
        id=LECTURE_ID,
        title="SE1 L1: Organisation and why software engineering",
        audio_url="http://localhost:8000/api/media/dummy.mp3",
        duration_seconds=1762,
        transcript_segments=[
            TranscriptSegment(
                start=0.0,
                end=8.5,
                text_original="Wir haben eine online bekanntgegebene Anwesenheit.",
                text_translated="We have an online attendance announcement.",
            ),
            TranscriptSegment(
                start=8.6,
                end=16.1,
                text_original="Abmeldungen sind noch bis zum 4.10. möglich.",
                text_translated="Deregistrations are still possible until 4.10.",
            ),
        ],
    )


@router.get("/courses/{course_id}/mindmap", response_model=MindMapResponse, tags=["courses"])
def course_mindmap(course_id: uuid.UUID):
    a, b = uuid.uuid4(), uuid.uuid4()
    return MindMapResponse(
        nodes=[
            MindMapNode(id=a, label="Software engineering", summary="Building maintainable systems."),
            MindMapNode(id=b, label="Technical debt", summary="Shortcuts that compound over time."),
        ],
        edges=[MindMapEdge(source=str(a), target=str(b), relation="causes")],
    )


@router.get("/jobs/status-values", response_model=list[FileProcessingStatus], tags=["jobs"])
def status_values():
    return list(FileProcessingStatus)
