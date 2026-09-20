import uuid
import datetime

from pydantic import BaseModel

class Course(BaseModel):
    id: uuid.UUID
    name: str

class CourseSummary(Course):
    lecture_count: int
    document_count: int
    last_activity_at: datetime.datetime
    has_active_jobs: bool
