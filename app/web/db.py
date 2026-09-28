from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine_options = {"echo": False, "pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    engine_options.update(pool_size=5, max_overflow=10)
engine = create_async_engine(settings.database_url, **engine_options)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
