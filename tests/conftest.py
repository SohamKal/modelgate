"""Offline test configuration never reads provider secrets from the environment."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.settings import Settings


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-postgres", action="store_true", help="Fail if TEST_DATABASE_URL is absent."
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    if session.config.getoption("--require-postgres") and not os.environ.get("TEST_DATABASE_URL"):
        raise pytest.UsageError("TEST_DATABASE_URL is required for the database completion gate.")


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith(("MODELGATE_", "OPENAI_", "GROQ_")) or name == "DATABASE_URL":
            monkeypatch.delenv(name)


@pytest.fixture(scope="session")
def postgres_url() -> str:
    from sqlalchemy.engine import make_url

    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for PostgreSQL integration; CI requires it.")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+asyncpg" or not (parsed.database or "").endswith("_test"):
        raise pytest.UsageError(
            "Database tests require an explicit PostgreSQL database ending in _test."
        )
    test_env = os.environ.copy()
    test_env["DATABASE_URL"] = url
    subprocess.run(
        [str(Path(".venv/bin/alembic").resolve()), "upgrade", "head"], env=test_env, check=True
    )
    return url


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, client_api_key=SecretStr("synthetic-gateway-credential"))


@pytest.fixture
def headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.client_api_key.get_secret_value()}"}


@pytest.fixture
def payload() -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": "Synthetic test request."}]}


@pytest.fixture
def openai_response() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "openai_completed.json"
    return json.loads(path.read_text())  # type: ignore[no-any-return]
