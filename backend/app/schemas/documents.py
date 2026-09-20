import uuid
import datetime
from typing import Literal

from pydantic import BaseModel

from .enums import FileProcessingStatus
from .courses import Course
from .lectures import Lecture

class File(BaseModel):
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


