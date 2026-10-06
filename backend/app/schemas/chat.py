import uuid
from typing import Literal

from app.schemas.base import ApiModel


class ChatSource(ApiModel):
    kind: Literal["transcript", "english", "slides", "web"]
    ref: str
    snippet: str
    title: str  # lecture / document title, or the web page title
    lecture_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    start: float | None = None  # seconds: lecture timeline (transcript) or English audio (english)
    page: int | None = None
    url: str | None = None


class ChatMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str
    sources: list[ChatSource] = []


class ChatRequest(ApiModel):
    message: str
    course_id: uuid.UUID
    # What the answer may draw on. A lecture's own chat sends just that lecture.
    lecture_ids: list[uuid.UUID] = []
    document_ids: list[uuid.UUID] = []
    thread_id: uuid.UUID | None = None
    web: bool = False  # also search the web (needs TAVILY_API_KEY)


class ChatResponse(ApiModel):
    thread_id: uuid.UUID
    message: ChatMessage


class ChatHistory(ApiModel):
    thread_id: uuid.UUID | None
    messages: list[ChatMessage]


class ChatSelection(ApiModel):
    """The sources last used in a course's chat (remembered between visits)."""

    lecture_ids: list[uuid.UUID] = []
    document_ids: list[uuid.UUID] = []
    web: bool = False
