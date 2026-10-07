"""Shared local CLI lifecycle; diagnostic messages never include connection values."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.settings import Settings
from app.persistence.repositories import Repository
from app.persistence.session import create_engine, sessions


@asynccontextmanager
async def repository(settings: Settings) -> AsyncIterator[Repository]:
    engine = create_engine(settings)
    try:
        yield Repository(sessions(engine))
    finally:
        await engine.dispose()
