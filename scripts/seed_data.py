"""Repeatable offline seed; never resets an existing active configuration."""

import asyncio
import json
import sys

from app.core.settings import Settings
from scripts.database import repository


async def seed() -> int:
    settings = Settings(stable_release="fake")  # type: ignore[call-arg]
    async with repository(settings) as repo:
        version = await repo.seed()
        print(json.dumps({"active_version": version, "provider_calls": 0}))
    return 0


def main() -> int:
    try:
        return asyncio.run(seed())
    except Exception:
        print(
            "Seed failed; check migrations, database access and release definitions.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
