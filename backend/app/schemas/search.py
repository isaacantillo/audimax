import uuid
from typing import Literal

from app.schemas.base import ApiModel


class SearchHit(ApiModel):
    lecture_id: uuid.UUID
    lecture_title: str
    course_id: uuid.UUID
    kind: Literal["transcript", "english"]
    start: float  # seconds on the lecture timeline: the sentence, or where the paragraph begins in the original
    paragraph_id: str | None  # english hits: which paragraph of the English version ("03.02")
    text: str  # the German sentence, or the English script paragraph
    text_translated: str | None  # English translation of a German sentence


class SearchResponse(ApiModel):
    query: str
    hits: list[SearchHit]
    truncated: bool  # more matches exist than were returned
