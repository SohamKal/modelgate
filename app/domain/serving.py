"""One serving attempt within a total deadline, including response validation."""

import asyncio

from pydantic import ValidationError

from app.core.errors import ProviderError
from app.domain.contracts import ChatRequest, ProviderResult, Release
from app.providers.base import Provider


async def invoke(
    provider: Provider, request: ChatRequest, release: Release, deadline_seconds: float
) -> ProviderResult:
    try:
        async with asyncio.timeout(deadline_seconds):
            result = await provider.complete(request, release)
            return ProviderResult.model_validate(result)
    except TimeoutError:
        raise ProviderError("provider_timeout") from None
    except ValidationError:
        raise ProviderError("invalid_provider_response") from None
