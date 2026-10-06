import uuid
from typing import Literal

from app.schemas.base import ApiModel


class SearchHit(ApiModel):
    lecture_id: uuid.UUID
    lecture_title: str
    course_id: uuid.UUID
    kind: Literal["transcript", "english"]
    # transcript: seconds on the lecture timeline (the original recordings);
    # english: seconds in the English audio.
    start: float
    text: str  # the German sentence, or the English script paragraph
    text_translated: str | None  # English translation of a German sentence


class SearchResponse(ApiModel):
    query: str
    hits: list[SearchHit]
    truncated: bool  # more matches exist than were returned
