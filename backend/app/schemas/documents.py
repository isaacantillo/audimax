import datetime
import uuid
from typing import Literal

from app.schemas.base import ApiModel

from .courses import Course
from .enums import FileProcessingStatus
from .lectures import Lecture


class File(ApiModel):
    id: uuid.UUID
    title: str


class DocumentSummary(File):
    type: Literal["slides"]
    status: FileProcessingStatus
    course: Course
    lecture: Lecture | None


class AudioSummary(File):
    date: datetime.date
    duration_seconds: int
    status: FileProcessingStatus


class DocumentSection(ApiModel):
    page: int
    heading: str | None
    text: str


class DocumentDetails(DocumentSummary):
    file_url: str
    page_count: int
    error: str | None = None
    sections: list[DocumentSection]
