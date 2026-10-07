"""Load the ignored environment and apply Alembic without printing connection secrets."""

import os
import sys

from alembic import command
from alembic.config import Config

from app.core.settings import Settings


def main() -> int:
    try:
        settings = Settings(stable_release="fake")  # type: ignore[call-arg]
        if settings.database_url is None:
            raise ValueError("Database setting missing.")
        os.environ["DATABASE_URL"] = settings.database_url.get_secret_value()
        command.upgrade(Config("alembic.ini"), "head")
        return 0
    except Exception:
        print("Migration failed; check database access and migration state.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
