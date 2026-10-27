import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str]
    # Sees and manages every user's courses; everyone else only their own.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    """Opaque token, stored hashed. `kind` splits browser cookies from long-lived API tokens."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # "browser" | "api"
    name: Mapped[str | None]
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))  # None = no expiry
    # Where the session is used from, refreshed as it is used (see app.auth.touch).
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[str | None] = mapped_column(String(200))  # "City, Region, Country" from the IP
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
