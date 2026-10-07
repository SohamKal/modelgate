"""Groq Responses adapter with its documented stateless parameter subset."""

import httpx

from app.domain.contracts import ChatRequest, Release
from app.providers.openai import OpenAIProvider

GPT_OSS_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}


class GroqProvider(OpenAIProvider):
    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        super().__init__(client, api_key, base_url="https://api.groq.com/openai/v1")

    def build_body(self, request: ChatRequest, release: Release) -> dict[str, object]:
        body = super().build_body(request, release)
        # Groq has no stateful response storage and explicitly rejects this parameter.
        body.pop("store")
        # Only request synchronous serving; do not rely on undocumented background support.
        body.pop("background")
        if release.model in GPT_OSS_MODELS:
            body["reasoning"] = {"effort": "low"}
        return body
