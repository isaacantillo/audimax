# Import every model so Alembic's autogenerate sees them on Base.metadata.
from app.models.content import (
    Chunk,
    Course,
    GlossaryTerm,
    Lecture,
    LecturePart,
    Paragraph,
    Unit,
)
from app.models.user import AuthSession, User

__all__ = ["AuthSession", "Chunk", "Course", "GlossaryTerm", "Lecture", "LecturePart", "Paragraph", "Unit", "User"]
