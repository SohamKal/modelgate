import copy
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.errors import ProviderError
from app.core.settings import Settings
from app.domain.contracts import ChatRequest, Release
from app.main import create_app
from app.providers.groq import GroqProvider
from app.providers.openai import normalize_response
from scripts.verify_models import verify


@pytest.fixture
def groq_response(openai_response: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(openai_response)
    payload["model"] = "openai/gpt-oss-20b"
    payload["output"][0] = {
        "type": "reasoning",
        "status": "completed",
        "content": [{"type": "reasoning_text", "text": "private-reasoning-marker"}],
        "summary": [],
    }
    return payload


def groq_settings(settings: Settings, active: str = "fake") -> Settings:
    return Settings.model_validate(
        settings.model_dump()
        | {
            "verification_provider": "groq",
            "stable_release": active,
            "groq_api_key": SecretStr("synthetic-groq-credential"),
            "groq_model_a": "openai/gpt-oss-20b",
            "groq_model_b": "openai/gpt-oss-120b",
        }
    )


def test_reasoning_text_is_discarded_before_content_validation(
    groq_response: dict[str, Any],
) -> None:
    result = normalize_response(groq_response)
    assert result.content == "Synthetic answer."
    assert "private-reasoning-marker" not in result.model_dump_json()
    assert result.usage is not None and result.usage.total_tokens == 20


@pytest.mark.parametrize(
    "name,model",
    [
        ("groq-a", "openai/gpt-oss-20b"),
        ("groq-b", "openai/gpt-oss-120b"),
    ],
)
async def test_groq_adapter_request_and_response(
    payload: dict[str, Any],
    groq_response: dict[str, Any],
    name: Any,
    model: str,
) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=groq_response | {"model": model})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await GroqProvider(client, "synthetic-groq-credential").complete(
            ChatRequest.model_validate(payload),
            Release(name=name, provider="groq", model=model, supports_temperature=False),
        )
    assert result.model == model
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.groq.com/openai/v1/responses"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-groq-credential"
    body = json.loads(requests[0].content)
    assert body == {
        "model": model,
        "input": payload["messages"],
        "max_output_tokens": 200,
        "stream": False,
        "reasoning": {"effort": "low"},
    }


async def test_live_verification_uses_two_distinct_groq_models(
    settings: Settings,
    groq_response: dict[str, Any],
) -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["model"])
        assert body["max_output_tokens"] == 512
        assert "store" not in body and "background" not in body
        return httpx.Response(200, json=groq_response | {"model": body["model"]})

    results = await verify(groq_settings(settings), httpx.MockTransport(handle))
    assert seen == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    assert [result["release"] for result in results] == ["groq-a", "groq-b"]
    assert all(result["status"] == "verified" for result in results)
    assert all(result["provider"] == "groq" for result in results)
    assert "private-reasoning-marker" not in json.dumps(results)


@pytest.mark.parametrize(
    "changes",
    [
        {"groq_api_key": None},
        {"groq_model_b": None},
        {"groq_model_a": "same", "groq_model_b": "same"},
    ],
)
def test_missing_or_duplicate_groq_configuration(
    settings: Settings, changes: dict[str, Any]
) -> None:
    config = groq_settings(settings)
    with pytest.raises(ValidationError):
        Settings.model_validate(config.model_dump() | changes | {"stable_release": "groq-a"})


def test_groq_credential_is_separate_from_gateway_key(settings: Settings) -> None:
    with pytest.raises(ValidationError, match="must be different"):
        Settings.model_validate(settings.model_dump() | {"groq_api_key": settings.client_api_key})


async def test_groq_rate_limit_is_safe_and_single_attempt(
    payload: dict[str, Any],
) -> None:
    count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(429, text="private-provider-error", headers={"Retry-After": "3"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError) as caught:
            await GroqProvider(client, "synthetic-groq-credential").complete(
                ChatRequest.model_validate(payload),
                Release(
                    name="groq-a",
                    provider="groq",
                    model="openai/gpt-oss-20b",
                    supports_temperature=False,
                ),
            )
    assert count == 1 and caught.value.code == "provider_rate_limited"
    assert caught.value.retry_after == 3
    assert "private-provider-error" not in str(caught.value)


async def test_gateway_selects_groq_and_keeps_public_contract(
    settings: Settings,
    payload: dict[str, Any],
    groq_response: dict[str, Any],
) -> None:
    config = groq_settings(settings, "groq-b")
    app = create_app(
        config,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=groq_response | {"model": "openai/gpt-oss-120b"}
            )
        ),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        result = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {config.client_api_key.get_secret_value()}"},
        )
    assert result.status_code == 200
    assert result.json()["release_name"] == "groq-b"
    assert result.json()["serving_role"] == "stable"
    assert result.json()["config_version"] is None
