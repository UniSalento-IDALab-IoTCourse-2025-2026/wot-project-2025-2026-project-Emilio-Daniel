from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def create_database_engine(database_url: str | None = None):
    """Crea un engine SQLAlchemy per codice applicativo e test."""
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Dependency FastAPI che apre e chiude una sessione database."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
