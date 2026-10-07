"""M2.0b: actual TCP requests, deadlines, cancellation and client cleanup."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from app.core.errors import ProviderError
from app.domain.contracts import ChatRequest, Release
from app.domain.serving import invoke
from app.providers.openai import OpenAIProvider


@asynccontextmanager
async def local_server(
    body: dict[str, Any], delay: float
) -> AsyncIterator[tuple[str, asyncio.Event, list[bytes]]]:
    started = asyncio.Event()
    requests: list[bytes] = []
    handlers: set[asyncio.Task[Any]] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        handlers.add(task)
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in header.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            requests.append(await reader.readexactly(length))
            started.set()
            await asyncio.sleep(delay)
            data = json.dumps(body).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(data)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + data
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/v1", started, requests
    finally:
        server.close()
        pending = list(handlers)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await server.wait_closed()


def release() -> Release:
    return Release(name="openai-a", provider="openai", model="model-a", supports_temperature=False)


async def test_real_http_normalization(
    payload: dict[str, Any], openai_response: dict[str, Any]
) -> None:
    async with local_server(openai_response, 0) as (url, _, requests):
        async with httpx.AsyncClient(trust_env=False) as client:
            result = await invoke(
                OpenAIProvider(client, "synthetic-credential", url),
                ChatRequest.model_validate(payload),
                release(),
                1,
            )
        assert client.is_closed and len(requests) == 1
        assert result.content == "Synthetic answer."


async def test_real_http_timeout(payload: dict[str, Any], openai_response: dict[str, Any]) -> None:
    async with local_server(openai_response, 10) as (url, started, requests):
        async with httpx.AsyncClient(trust_env=False) as client:
            before = time.monotonic()
            with pytest.raises(ProviderError) as caught:
                await asyncio.wait_for(
                    invoke(
                        OpenAIProvider(client, "synthetic-credential", url),
                        ChatRequest.model_validate(payload),
                        release(),
                        0.1,
                    ),
                    timeout=1,
                )
            assert caught.value.code == "provider_timeout"
            assert time.monotonic() - before < 1
        assert started.is_set() and len(requests) == 1 and client.is_closed


async def test_real_http_cancellation(
    payload: dict[str, Any], openai_response: dict[str, Any]
) -> None:
    async with local_server(openai_response, 10) as (url, started, requests):
        async with httpx.AsyncClient(trust_env=False) as client:
            task = asyncio.create_task(
                invoke(
                    OpenAIProvider(client, "synthetic-credential", url),
                    ChatRequest.model_validate(payload),
                    release(),
                    10,
                )
            )
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            before = time.monotonic()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert time.monotonic() - before < 1
        assert len(requests) == 1 and client.is_closed
