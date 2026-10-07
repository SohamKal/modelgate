from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from app.core.settings import Settings
from app.domain.contracts import ChatRequest, ProviderResult, Usage


@pytest.mark.parametrize(
    "changes",
    [
        {"messages": []},
        {"messages": [{"role": "tool", "content": "unsupported"}]},
        {"messages": [{"role": "user", "content": ""}]},
        {"messages": [{"role": "user", "content": "x"}] * 33},
        {"max_output_tokens": 0},
        {"max_output_tokens": True},
        {"temperature": -1},
        {"temperature": 3},
        {"stream": True},
    ],
)
def test_invalid_requests(payload: dict[str, Any], changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload | changes)


def test_request_defaults_and_optional_usage(payload: dict[str, Any]) -> None:
    request = ChatRequest.model_validate(payload)
    assert request.max_output_tokens == 200
    assert request.temperature is None
    assert ProviderResult(content="answer", model="test").usage is None
    assert Usage(input_tokens=3).output_tokens is None
    with pytest.raises(ValidationError):
        Usage(input_tokens=-1)


def test_configuration_requires_gateway_key() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"openai_api_key": SecretStr("synthetic-upstream-credential")},
        {
            "openai_api_key": SecretStr("synthetic-upstream-credential"),
            "openai_model_a": "same",
            "openai_model_b": "same",
        },
    ],
)
def test_real_serving_requires_two_models(settings: Settings, overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(settings.model_dump() | {"stable_release": "openai-a"} | overrides)


def test_keys_are_hidden_from_repr(settings: Settings) -> None:
    assert settings.client_api_key.get_secret_value() not in repr(settings)


def test_provider_key_cannot_be_used_as_gateway_key(settings: Settings) -> None:
    with pytest.raises(ValidationError, match="must be different"):
        Settings.model_validate(
            settings.model_dump()
            | {
                "openai_api_key": settings.client_api_key,
            }
        )
