"""SQLAlchemy 2.0 engine + sessionmaker factories."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..settings import Settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = Settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


__all__ = ["get_engine", "get_sessionmaker"]
