"""Single-host container startup: migrate, seed without reset, then replace with Uvicorn."""

import os

from scripts.migrate import main as migrate
from scripts.seed_data import main as seed


def main() -> int:
    if migrate() != 0 or seed() != 0:
        return 2
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
