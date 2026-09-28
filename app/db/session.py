"""Async engine и session maker (SQLite; позже PostgreSQL)."""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import settings

_connect_args: dict[str, Any] = {}
_engine_kwargs: dict[str, Any] = {
    "echo": False,
    "pool_pre_ping": True,
}

if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
    if ":memory:" in settings.database_url:
        _engine_kwargs["poolclass"] = StaticPool

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    connect_args=_connect_args,
    **_engine_kwargs,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session
