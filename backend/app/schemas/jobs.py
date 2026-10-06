import datetime
import uuid
from typing import Literal

from app.schemas.base import ApiModel


class JobSummary(ApiModel):
    id: int
    task: str
    queue: str
    status: Literal["todo", "doing", "succeeded", "failed", "cancelled", "aborting", "aborted"]
    lecture_id: uuid.UUID | None = None
    lecture_title: str | None = None
    scheduled_at: datetime.datetime
    attempts: int
    error: str | None = None  # the lecture's failure reason, when there is one
