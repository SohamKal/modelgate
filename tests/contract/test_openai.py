import json
from typing import Any

import httpx
import pytest

from app.core.errors import ProviderError
from app.domain.contracts import ChatRequest, Release
from app.providers.openai import OpenAIProvider, normalize_response


def test_normalization_preserves_usage_and_drops_provider_details(
    openai_response: dict[str, Any],
) -> None:
    result = normalize_response(openai_response)
    assert result.content == "Synthetic answer."
    assert result.usage is not None and result.usage.output_tokens == 8
    assert "reasoning" not in result.model_dump_json()


def test_absent_and_partial_usage_remain_unknown(openai_response: dict[str, Any]) -> None:
    openai_response.pop("usage")
    assert normalize_response(openai_response).usage is None
    openai_response["usage"] = {"input_tokens": 12}
    usage = normalize_response(openai_response).usage
    assert usage is not None and usage.total_tokens is None


@pytest.mark.parametrize(
    "mutations",
    [
        {"output": []},
        {"output": "not-an-array"},
        {"model": ""},
        {
            "output": [
                {"type": "message", "role": "assistant", "content": [{"type": "output_text"}]}
            ]
        },
        {"output": [{"type": "function_call"}]},
        {"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 99}},
        {"usage": {"input_tokens": True}},
        {"status": "queued"},
        {"status": "incomplete", "incomplete_details": {"reason": "unknown"}},
    ],
)
def test_malformed_responses_are_safe(
    openai_response: dict[str, Any], mutations: dict[str, Any]
) -> None:
    with pytest.raises(ProviderError) as caught:
        normalize_response(openai_response | mutations)
    assert caught.value.code == "invalid_provider_response"


def test_incomplete_and_refusal(openai_response: dict[str, Any]) -> None:
    limited = openai_response | {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    assert normalize_response(limited).finish_reason == "length"
    refusal = openai_response | {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "refusal", "refusal": "Declined."}],
            }
        ]
    }
    assert normalize_response(refusal).finish_reason == "content_filter"


@pytest.mark.parametrize("name,model", [("openai-a", "model-a"), ("openai-b", "model-b")])
async def test_same_contract_for_both_configs(
    payload: dict[str, Any], openai_response: dict[str, Any], name: Any, model: str
) -> None:
    captured: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=openai_response | {"model": model})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await OpenAIProvider(client, "synthetic-upstream-credential").complete(
            ChatRequest.model_validate(payload),
            Release(name=name, provider="openai", model=model, supports_temperature=False),
        )
    assert result.model == model
    assert captured == [
        {
            "model": model,
            "input": payload["messages"],
            "max_output_tokens": 200,
            "store": False,
            "stream": False,
            "background": False,
        }
    ]


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_authentication"),
        (403, "provider_authentication"),
        (429, "provider_rate_limited"),
        (400, "provider_request_rejected"),
        (500, "provider_unavailable"),
        (503, "provider_unavailable"),
        (302, "invalid_provider_response"),
        (404, "invalid_provider_response"),
    ],
)
async def test_http_failures_make_only_one_attempt(
    payload: dict[str, Any], status: int, code: str
) -> None:
    count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(status, text="private-upstream-body", headers={"Retry-After": "2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError) as caught:
            await OpenAIProvider(client, "synthetic-upstream-credential").complete(
                ChatRequest.model_validate(payload),
                Release(
                    name="openai-a", provider="openai", model="model-a", supports_temperature=False
                ),
            )
    assert count == 1
    assert caught.value.code == code
    assert "private-upstream-body" not in str(caught.value)
    if status == 429:
        assert caught.value.retry_after == 2


@pytest.mark.parametrize("kind", ["invalid-json", "too-large", "timeout", "disconnect"])
async def test_transport_and_body_failures(payload: dict[str, Any], kind: str) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if kind == "timeout":
            raise httpx.ReadTimeout("private-transport-details")
        if kind == "disconnect":
            raise httpx.ConnectError("private-transport-details")
        return httpx.Response(200, content=b"x" * (262145 if kind == "too-large" else 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderError) as caught:
            await OpenAIProvider(client, "synthetic-credential").complete(
                ChatRequest.model_validate(payload),
                Release(
                    name="openai-a", provider="openai", model="model-a", supports_temperature=False
                ),
            )
    assert "private-transport-details" not in str(caught.value)
    assert (
        caught.value.code
        == {
            "timeout": "provider_timeout",
            "disconnect": "provider_unavailable",
            "invalid-json": "invalid_provider_response",
            "too-large": "invalid_provider_response",
        }[kind]
    )


async def test_supported_temperature_is_forwarded(
    payload: dict[str, Any], openai_response: dict[str, Any]
) -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=openai_response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await OpenAIProvider(client, "synthetic-credential").complete(
            ChatRequest.model_validate(payload | {"temperature": 0}),
            Release(name="openai-a", provider="openai", model="model-a", supports_temperature=True),
        )
    assert seen[0]["temperature"] == 0


async def test_oversized_retry_header_preserves_normalized_rate_limit(
    payload: dict[str, Any],
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": "9" * 5000})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ProviderError) as caught:
            await OpenAIProvider(client, "synthetic-credential").complete(
                ChatRequest.model_validate(payload),
                Release(
                    name="openai-a", provider="openai", model="model-a", supports_temperature=False
                ),
            )
    assert caught.value.code == "provider_rate_limited"
    assert caught.value.retry_after is None
