"""Database resources are scoped to application/CLI lifespan."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    if settings.database_url is None:
        raise ValueError("DATABASE_URL is required for persistent serving.")
    return create_async_engine(
        settings.database_url.get_secret_value(),
        echo=False,
        hide_parameters=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=settings.database_deadline_seconds,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.database_deadline_seconds,
            "command_timeout": settings.database_deadline_seconds,
        },
    )


def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
