"""OpenAI Responses adapter; upstream shapes are isolated in this module."""

import json
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import ProviderError
from app.domain.contracts import ChatRequest, ProviderResult, Release, Usage

MAX_PROVIDER_BYTES = 262144


class _Part(BaseModel):
    model_config = ConfigDict(strict=True)
    type: Literal["output_text", "refusal"]
    text: str | None = None
    refusal: str | None = None


class _Item(BaseModel):
    model_config = ConfigDict(strict=True)
    type: Literal["message"]
    role: str | None = None
    content: list[_Part] = Field(default_factory=list)


class _Reasoning(BaseModel):
    model_config = ConfigDict(strict=True)
    type: Literal["reasoning"]
    # Reasoning content is deliberately not parsed or retained in our result.


class _Response(BaseModel):
    model_config = ConfigDict(strict=True)
    model: str = Field(min_length=1)
    status: Literal["completed", "incomplete", "failed", "cancelled", "queued", "in_progress"]
    output: list[Annotated[_Item | _Reasoning, Field(discriminator="type")]]
    usage: Usage | None = None
    incomplete_details: dict[str, str] | None = None


def normalize_response(payload: object) -> ProviderResult:
    """Extract text only; neither reasoning nor arbitrary tool output is returned."""
    try:
        # Provider usage has extra breakdown fields; retain only our three known counters.
        if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
            payload = {
                **payload,
                "usage": {
                    key: payload["usage"].get(key)
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                },
            }
        response = _Response.model_validate(payload)
        if response.status == "failed":
            raise ProviderError("provider_unavailable")
        if response.status not in {"completed", "incomplete"}:
            raise ProviderError("invalid_provider_response")
        fragments: list[str] = []
        refused = False
        for item in response.output:
            if item.type == "reasoning":
                continue
            if item.role != "assistant":
                raise ProviderError("invalid_provider_response")
            for part in item.content:
                value = part.text if part.type == "output_text" else part.refusal
                if value is None:
                    raise ProviderError("invalid_provider_response")
                fragments.append(value)
                refused = refused or part.type == "refusal"
        finish: Literal["stop", "length", "content_filter"] = "stop"
        if response.status == "incomplete":
            reason = (response.incomplete_details or {}).get("reason")
            if reason == "max_output_tokens":
                finish = "length"
            elif reason == "content_filter":
                finish = "content_filter"
            else:
                raise ProviderError("invalid_provider_response")
        if refused:
            finish = "content_filter"
        if not fragments and finish == "stop":
            raise ProviderError("invalid_provider_response")
        usage = response.usage
        if usage is not None:
            counts = (usage.input_tokens, usage.output_tokens, usage.total_tokens)
            if all(count is not None for count in counts):
                assert usage.input_tokens is not None and usage.output_tokens is not None
                if usage.total_tokens != usage.input_tokens + usage.output_tokens:
                    raise ProviderError("invalid_provider_response")
        return ProviderResult(
            content="".join(fragments), model=response.model, usage=usage, finish_reason=finish
        )
    except ValidationError:
        raise ProviderError("invalid_provider_response") from None


class OpenAIProvider:
    def __init__(
        self, client: httpx.AsyncClient, api_key: str, base_url: str = "https://api.openai.com/v1"
    ) -> None:
        self.client = client
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/responses"

    def build_body(self, request: ChatRequest, release: Release) -> dict[str, object]:
        if request.temperature is not None and not release.supports_temperature:
            raise ProviderError("invalid_request")
        body: dict[str, object] = {
            "model": release.model,
            "input": [message.model_dump() for message in request.messages],
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "stream": False,
            "background": False,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        return body

    async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
        body = self.build_body(request, release)
        try:
            async with self.client.stream(
                "POST",
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            ) as response:
                if response.status_code in {401, 403}:
                    raise ProviderError("provider_authentication")
                if response.status_code == 429:
                    retry = response.headers.get("Retry-After", "")
                    delay = (
                        min(int(retry), 3600)
                        if len(retry) <= 6 and retry.isascii() and retry.isdigit()
                        else None
                    )
                    raise ProviderError("provider_rate_limited", delay)
                if response.status_code >= 500:
                    raise ProviderError("provider_unavailable")
                if response.status_code == 400:
                    raise ProviderError("provider_request_rejected")
                if response.status_code != 200:
                    raise ProviderError("invalid_provider_response")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > MAX_PROVIDER_BYTES:
                        raise ProviderError("invalid_provider_response")
                    data.extend(chunk)
                try:
                    payload = json.loads(data)
                except (ValueError, UnicodeDecodeError):
                    raise ProviderError("invalid_provider_response") from None
                return normalize_response(payload)
        except httpx.TimeoutException:
            raise ProviderError("provider_timeout") from None
        except httpx.TransportError:
            raise ProviderError("provider_unavailable") from None
