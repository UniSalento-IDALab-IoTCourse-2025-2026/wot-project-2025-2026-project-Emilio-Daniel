from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamps for database defaults."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class TimestampMixin:
    """Common created/updated timestamps for mutable backend records."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
