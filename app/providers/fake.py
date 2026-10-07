"""Offline deterministic adapter. Fault injection is constructor-only."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from app.core.errors import ProviderError
from app.domain.contracts import ChatRequest, ProviderResult, Release, Usage


@dataclass(frozen=True)
class FakeBehavior:
    latency_seconds: float = 0
    outcome: Literal["success", "unavailable", "malformed"] = "success"


class FakeProvider:
    def __init__(self, behavior: FakeBehavior | None = None) -> None:
        self.behavior = behavior or FakeBehavior()

    async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
        await asyncio.sleep(self.behavior.latency_seconds)
        if self.behavior.outcome == "unavailable":
            raise ProviderError("provider_unavailable")
        if self.behavior.outcome == "malformed":
            raise ProviderError("invalid_provider_response")
        canonical = json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        content = f"fake:{digest}"
        # Synthetic counts: reproducible fixture data, not a real tokenizer or cost estimate.
        input_tokens = sum(len(message.content.split()) for message in request.messages)
        return ProviderResult(
            content=content,
            model=release.model,
            usage=Usage(input_tokens=input_tokens, output_tokens=1, total_tokens=input_tokens + 1),
            finish_reason="stop",
        )
