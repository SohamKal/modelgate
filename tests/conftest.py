"""Offline test configuration never reads provider secrets from the environment."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.settings import Settings


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith(("MODELGATE_", "OPENAI_", "GROQ_")):
            monkeypatch.delenv(name)


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
