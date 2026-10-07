import datetime
import uuid

from app.schemas.base import ApiModel

from .enums import LectureStatus


class Lecture(ApiModel):
    id: uuid.UUID
    title: str


class LectureSummary(Lecture):
    summary: str
    status: LectureStatus = LectureStatus.ready
    duration_seconds: int = 0
    date: datetime.date | None = None
    has_english: bool = False


class TranscriptSegment(ApiModel):
    start: float
    end: float
    text_original: str
    text_translated: str | None


class LecturePart(ApiModel):
    """One recording of the lecture. `offset` places it on the shared timeline."""

    n: int
    filename: str
    offset: float
    duration: float
    audio_url: str


class EnglishParagraph(ApiModel):
    id: str  # "03.02" = chunk 3, paragraph 2
    text: str
    source_start: float  # where the German original begins, on the lecture timeline
    source_part: int  # which recording that falls in...
    source_part_start: float  # ...and the time within that file ("hear original")


class EnglishChunk(ApiModel):
    n: int
    title: str
    status: str  # pending | done | skipped
    verified: bool
    attempts: int
    paragraphs: list[EnglishParagraph]


class EnglishLecture(ApiModel):
    """The re-performed lecture as text, paragraph by paragraph, each linked to its place in the original."""

    chunks: list[EnglishChunk]


class TranscriptDetails(ApiModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    status: LectureStatus
    error: str | None = None
    audio_url: str  # first recording; see `parts` for all of them
    duration_seconds: int
    parts: list[LecturePart]
    transcript_segments: list[TranscriptSegment]
    english: EnglishLecture | None = None
