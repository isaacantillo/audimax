import datetime
import uuid

from app.schemas.base import ApiModel


class Course(ApiModel):
    id: uuid.UUID
    name: str

class CourseSummary(Course):
    added_by: str  # username of the course's owner
    lecture_count: int
    last_activity_at: datetime.datetime
    has_active_jobs: bool


class CourseCreate(ApiModel):
    name: str
