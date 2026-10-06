import datetime
import uuid
from typing import Any

from sqlalchemy import (
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

from app.db import Base

_now = func.now()


def _fk(table: str) -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey(f"{table}.id", ondelete="CASCADE"), index=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
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
