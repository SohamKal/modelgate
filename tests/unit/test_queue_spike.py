"""M2.0c: prove nonblocking admission with a real bounded asyncio.Queue."""

import asyncio
from typing import Any

import pytest

from app.core.settings import Settings
from app.domain.contracts import ChatRequest
from app.providers.fake import FakeProvider


async def test_full_queue_does_not_hold_up_serving(
    settings: Settings, payload: dict[str, Any]
) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    queue.put_nowait("accepted")
    serving = asyncio.create_task(
        FakeProvider().complete(ChatRequest.model_validate(payload), settings.active_release())
    )
    with pytest.raises(asyncio.QueueFull):
        queue.put_nowait("skipped")
    result = await asyncio.wait_for(serving, timeout=1)
    assert result.finish_reason == "stop"
    assert queue.get_nowait() == "accepted"
