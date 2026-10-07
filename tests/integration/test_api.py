import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.core.settings import Settings
from app.domain.contracts import ChatRequest, ProviderResult, Release
from app.main import create_app
from app.providers.base import Provider
from app.providers.fake import FakeBehavior, FakeProvider


@asynccontextmanager
async def session(
    settings: Settings,
    provider: Provider | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app(settings, provider=provider, transport=transport, ephemeral=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        yield app, client


async def test_stable_endpoint_and_lifecycle(
    settings: Settings, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    async with session(settings) as (app, client):
        upstream = app.state.http_client
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 200
        assert (await client.get("/metrics/")).status_code == 200
        response = await client.post("/v1/chat/completions", headers=headers, json=payload)
        data = response.json()
        assert response.status_code == 200
        assert data["release_name"] == "fake" and data["serving_role"] == "stable"
        assert data["config_version"] is None
        assert str(UUID(data["request_id"])) == response.headers["x-request-id"]
        again = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert again.json()["content"] == data["content"]
        assert again.json()["request_id"] != data["request_id"]
        assert not upstream.is_closed
    assert upstream.is_closed and not app.state.ready


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic anything", "Bearer"])
async def test_authentication(
    settings: Settings, payload: dict[str, Any], authorization: str | None
) -> None:
    async with session(settings) as (_, client):
        response = await client.post(
            "/v1/chat/completions",
            json=payload,
            headers={} if authorization is None else {"Authorization": authorization},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"stream": True},
        {"model": "client-choice"},
        {"max_output_tokens": 1025},
        {"temperature": 3},
        {"messages": []},
    ],
)
async def test_invalid_requests(
    settings: Settings, headers: dict[str, str], payload: dict[str, Any], changes: dict[str, Any]
) -> None:
    async with session(settings) as (_, client):
        response = await client.post(
            "/v1/chat/completions", headers=headers, json=payload | changes
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "input" not in response.json()


async def test_actual_byte_limit_including_chunks(
    settings: Settings, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"x" * 32768
        yield b"y" * 32769

    async with session(settings) as (_, client):
        response = await client.post(
            "/v1/chat/completions", headers=headers | {"Content-Length": "0"}, content=chunks()
        )
        assert response.status_code == 413
        # Exactly the limit is allowed; a padded valid JSON body remains valid.
        import json

        raw = json.dumps(payload).encode()
        at_limit = raw + b" " * (65536 - len(raw))
        response = await client.post(
            "/v1/chat/completions",
            headers=headers | {"Content-Type": "application/json"},
            content=at_limit,
        )
        assert response.status_code == 200


async def test_timeout_restores_capacity(
    settings: Settings, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    settings = settings.model_copy(update={"serving_deadline_seconds": 0.01})
    async with session(settings, FakeProvider(FakeBehavior(latency_seconds=10))) as (app, client):
        response = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "provider_timeout"
        assert app.state.serving_slots.qsize() == settings.serving_concurrency


async def test_capacity_and_cancellation(
    settings: Settings, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    started, release_call = asyncio.Event(), asyncio.Event()

    class BlockingProvider:
        async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
            started.set()
            await release_call.wait()
            return ProviderResult(content="done", model=release.model, finish_reason="stop")

    async with session(
        settings.model_copy(update={"serving_concurrency": 1}), BlockingProvider()
    ) as (app, client):
        first = asyncio.create_task(
            client.post("/v1/chat/completions", headers=headers, json=payload)
        )
        await asyncio.wait_for(started.wait(), 1)
        second = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert second.status_code == 503 and second.json()["error"]["code"] == "serving_busy"
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert app.state.serving_slots.qsize() == 1
        release_call.set()
        assert (
            await client.post("/v1/chat/completions", headers=headers, json=payload)
        ).status_code == 200


@pytest.mark.parametrize("active,expected", [("openai-a", "model-a"), ("openai-b", "model-b")])
async def test_api_provider_interchangeability(
    settings: Settings,
    headers: dict[str, str],
    payload: dict[str, Any],
    openai_response: dict[str, Any],
    active: str,
    expected: str,
) -> None:
    configuration = Settings.model_validate(
        settings.model_dump()
        | {
            "stable_release": active,
            "openai_model_a": "model-a",
            "openai_model_b": "model-b",
            "openai_api_key": SecretStr("synthetic-upstream-credential"),
        }
    )
    count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(200, json=openai_response | {"model": expected})

    async with session(configuration, transport=httpx.MockTransport(handle)) as (_, client):
        assert (await client.get("/health/ready")).status_code == 200
        assert count == 0  # Readiness never performs a paid probe.
        response = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json()["release_name"] == active
        assert response.json()["model"] == expected
        rejected = await client.post(
            "/v1/chat/completions", headers=headers, json=payload | {"temperature": 0}
        )
        assert rejected.status_code == 422 and count == 1


async def test_safe_errors_and_logs(
    settings: Settings,
    headers: dict[str, str],
    payload: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    private = "synthetic-private-body-marker"

    class ExplodingProvider:
        async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
            raise RuntimeError(private + settings.client_api_key.get_secret_value())

    caplog.set_level(logging.INFO, logger="modelgate")
    async with session(settings, ExplodingProvider()) as (_, client):
        response = await client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"messages": [{"role": "user", "content": private}]},
        )
        assert response.status_code == 500
        invalid = await client.post("/v1/chat/completions", headers=headers, content=private)
        assert invalid.status_code == 422
    text = response.text + invalid.text + caplog.text
    assert private not in text
    assert settings.client_api_key.get_secret_value() not in text


async def test_upstream_auth_and_rate_limit_are_normalized(
    settings: Settings, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    configuration = Settings.model_validate(
        settings.model_dump()
        | {
            "stable_release": "openai-a",
            "openai_model_a": "model-a",
            "openai_model_b": "model-b",
            "openai_api_key": SecretStr("synthetic-upstream-credential"),
        }
    )
    for status, gateway_status, code in [
        (401, 502, "provider_authentication"),
        (429, 429, "provider_rate_limited"),
    ]:
        transport = httpx.MockTransport(
            lambda request, status=status: httpx.Response(
                status, text="private-upstream-text", headers={"Retry-After": "3"}
            )
        )
        async with session(configuration, transport=transport) as (_, client):
            response = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert response.status_code == gateway_status
        assert response.json()["error"]["code"] == code
        assert "private-upstream-text" not in response.text
        if status == 429:
            assert response.headers["retry-after"] == "3"
