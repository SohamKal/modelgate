"""Provider-neutral, text-only contracts for the stable gateway."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(Contract):
    messages: list[Message] = Field(min_length=1, max_length=32)
    task_type: str | None = Field(default=None, min_length=1, max_length=64)
    request_key: str | None = Field(default=None, min_length=1, max_length=128)
    max_output_tokens: int = Field(default=200, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)


class Usage(Contract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderResult(Contract):
    content: str
    model: str = Field(min_length=1)
    usage: Usage | None = None
    finish_reason: Literal["stop", "length", "content_filter", "unknown"] = "unknown"


class ChatResponse(ProviderResult):
    request_id: str
    release_name: str
    serving_role: Literal["stable"] = "stable"
    config_version: int | None = None


class Release(Contract):
    name: Literal["fake", "openai-a", "openai-b", "groq-a", "groq-b"]
    provider: Literal["fake", "openai", "groq"]
    model: str = Field(min_length=1, max_length=128)
    supports_temperature: bool
