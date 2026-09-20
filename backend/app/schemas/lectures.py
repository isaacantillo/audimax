import uuid

from pydantic import BaseModel, HttpUrl


class Lecture(BaseModel):
    id: uuid.UUID
    title: str


class LectureSummary(Lecture):
    document_count: int
    summary: str


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text_original: str
    text_translated: str | None


class TranscriptDetails(BaseModel):
    id: uuid.UUID
    title: str
    audio_url: HttpUrl
    duration_seconds: int
    transcript_segments: list[TranscriptSegment]
