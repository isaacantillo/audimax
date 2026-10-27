import uuid

from app.schemas.base import ApiModel


class SaveLiveRecording(ApiModel):
    course_id: uuid.UUID
    title: str = ""
    english: bool = False
