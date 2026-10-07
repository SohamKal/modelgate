"""Adapters implement one asynchronous, provider-neutral call."""

from typing import Protocol

from app.domain.contracts import ChatRequest, ProviderResult, Release


class Provider(Protocol):
    async def complete(self, request: ChatRequest, release: Release) -> ProviderResult: ...
