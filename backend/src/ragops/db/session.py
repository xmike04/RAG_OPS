"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ragops.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    options: dict[str, object] = {
        "echo": settings.database_echo,
        "pool_pre_ping": True,
    }
    if not settings.database_url.startswith("sqlite"):
        options.update(
            pool_size=settings.database_pool_size, max_overflow=settings.database_pool_size
        )
    return create_async_engine(settings.database_url, **options)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
