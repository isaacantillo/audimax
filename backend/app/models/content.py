import datetime
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base

_now = func.now()


def _fk(table: str) -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey(f"{table}.id", ondelete="CASCADE"), index=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    chat_selection: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # "remembers last selection"
    mindmap: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # cached course-wide map
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=_now)


class Lecture(Base):
    __tablename__ = "lectures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = _fk("courses")
    title: Mapped[str] = mapped_column(String(300))
    date: Mapped[datetime.date] = mapped_column(Date, server_default=func.current_date())
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    error: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[float] = mapped_column(Float, default=0)
    summary: Mapped[str | None] = mapped_column(Text)
    mindmap: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # English re-performed lecture
    tts_provider: Mapped[str | None] = mapped_column(String(20))
    english_audio_key: Mapped[str | None] = mapped_column(String(500))
    english_duration: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now, onupdate=_now
    )


class LecturePart(Base):
    """One uploaded recording. A lecture can have several; they share one timeline via `offset`."""

    __tablename__ = "lecture_parts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lecture_id: Mapped[uuid.UUID] = _fk("lectures")
    n: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(300))
    audio_key: Mapped[str] = mapped_column(String(500))
    duration: Mapped[float] = mapped_column(Float, default=0)
    offset: Mapped[float] = mapped_column(Float, default=0)
    transcript: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # raw provider output (words, segments)


class Unit(Base):
    """A sentence of the German transcript with its English translation, on the lecture timeline."""

    __tablename__ = "units"
    __table_args__ = (Index("ix_units_lecture_n", "lecture_id", "n", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lecture_id: Mapped[uuid.UUID] = _fk("lectures")
    n: Mapped[int] = mapped_column(Integer)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    text_de: Mapped[str] = mapped_column(Text)
    text_en: Mapped[str | None] = mapped_column(Text)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_lecture_n", "lecture_id", "n", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lecture_id: Mapped[uuid.UUID] = _fk("lectures")
    n: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    first_unit: Mapped[int] = mapped_column(Integer)
    last_unit: Mapped[int] = mapped_column(Integer)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    checklist: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    introduce: Mapped[list[str] | None] = mapped_column(JSONB)  # glossary terms first said here
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | done | skipped
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Paragraph(Base):
    __tablename__ = "paragraphs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lecture_id: Mapped[uuid.UUID] = _fk("lectures")
    chunk_id: Mapped[uuid.UUID] = _fk("chunks")
    chunk_n: Mapped[int] = mapped_column(Integer)
    n: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    first_unit: Mapped[int] = mapped_column(Integer)
    last_unit: Mapped[int] = mapped_column(Integer)
    clip_key: Mapped[str | None] = mapped_column(String(500))
    start: Mapped[float | None] = mapped_column(Float)  # position in the English audio
    end: Mapped[float | None] = mapped_column(Float)


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lecture_id: Mapped[uuid.UUID] = _fk("lectures")
    german: Mapped[str] = mapped_column(String(200))
    english: Mapped[str] = mapped_column(String(200))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = _fk("courses")
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lectures.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(300))
    file_key: Mapped[str] = mapped_column(String(500))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=_now)


class DocumentSection(Base):
    __tablename__ = "document_sections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = _fk("documents")
    n: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)


class Passage(Base):
    """Embedded text for retrieval: transcript windows, English script paragraphs, slide sections."""

    __tablename__ = "passages"
    __table_args__ = (
        Index(
            "ix_passages_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = _fk("courses")
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lectures.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))  # transcript | english | slides
    ref: Mapped[str] = mapped_column(String(60))  # unit range, paragraph id, or page
    start: Mapped[float | None] = mapped_column(Float)  # seconds in the matching audio
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dims))


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = _fk("courses")
    lecture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lectures.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=_now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = _fk("chat_threads")
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
