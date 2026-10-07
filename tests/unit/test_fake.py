import asyncio
from typing import Any

import pytest

from app.core.errors import ProviderError
from app.core.settings import Settings
from app.domain.contracts import ChatRequest
from app.domain.serving import invoke
from app.providers.fake import FakeBehavior, FakeProvider


async def test_repeatable_output_and_synthetic_usage(
    settings: Settings, payload: dict[str, Any]
) -> None:
    adapter = FakeProvider()
    request = ChatRequest.model_validate(payload)
    a = await adapter.complete(request, settings.active_release())
    b = await adapter.complete(request, settings.active_release())
    assert a == b
    assert a.usage is not None and a.usage.total_tokens == 4


@pytest.mark.parametrize(
    "outcome,code",
    [
        ("unavailable", "provider_unavailable"),
        ("malformed", "invalid_provider_response"),
    ],
)
async def test_fake_failures(
    settings: Settings, payload: dict[str, Any], outcome: Any, code: str
) -> None:
    with pytest.raises(ProviderError) as caught:
        await FakeProvider(FakeBehavior(outcome=outcome)).complete(
            ChatRequest.model_validate(payload), settings.active_release()
        )
    assert caught.value.code == code


async def test_deadline_and_external_cancellation(
    settings: Settings, payload: dict[str, Any]
) -> None:
    adapter = FakeProvider(FakeBehavior(latency_seconds=10))
    request = ChatRequest.model_validate(payload)
    with pytest.raises(ProviderError, match="deadline") as caught:
        await invoke(adapter, request, settings.active_release(), 0.01)
    assert caught.value.code == "provider_timeout"
    task = asyncio.create_task(invoke(adapter, request, settings.active_release(), 10))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
