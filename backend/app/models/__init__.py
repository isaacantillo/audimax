# Import every model so Alembic's autogenerate sees them on Base.metadata.
from app.models.content import (
    ChatMessage,
    ChatThread,
    Chunk,
    Course,
    Document,
    DocumentSection,
    GlossaryTerm,
    Lecture,
    LecturePart,
    Paragraph,
    Passage,
    Unit,
)
from app.models.user import AuthSession, User

__all__ = [
    "AuthSession",
    "ChatMessage",
    "ChatThread",
    "Chunk",
    "Course",
    "Document",
    "DocumentSection",
    "GlossaryTerm",
    "Lecture",
    "LecturePart",
    "Paragraph",
    "Passage",
    "Unit",
    "User",
]
