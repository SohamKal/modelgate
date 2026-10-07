"""Stable chat serving; release selection is exclusively server configuration."""

import asyncio
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import ERRORS, ErrorResponse, ProviderError, error_body
from app.core.settings import Settings
from app.domain.contracts import ChatRequest, ChatResponse, Release
from app.domain.serving import invoke
from app.providers.base import Provider

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    settings: Settings = request.app.state.settings
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.client_api_key.get_secret_value().encode()
    ):
        raise ProviderError("unauthorized")


@router.post(
    "/v1/chat/completions",
    response_model=ChatResponse,
    responses={
        status: {"model": ErrorResponse} for status in (401, 413, 422, 429, 500, 502, 503, 504)
    },
)
async def complete(
    body: ChatRequest, request: Request, authenticated: Annotated[None, Depends(authenticate)]
) -> ChatResponse | JSONResponse:
    settings: Settings = request.app.state.settings
    release: Release = request.app.state.release
    if body.max_output_tokens > settings.max_output_tokens:
        raise ProviderError("invalid_request")
    if body.temperature is not None and not release.supports_temperature:
        raise ProviderError("invalid_request")
    slots: asyncio.Queue[None] = request.app.state.serving_slots
    try:
        slots.get_nowait()
    except asyncio.QueueEmpty:
        raise ProviderError("serving_busy") from None
    request.state.release_name = release.name
    request.state.serving_role = "stable"
    try:
        provider: Provider = request.app.state.provider
        result = await invoke(provider, body, release, settings.serving_deadline_seconds)
        return ChatResponse(
            **result.model_dump(), request_id=request.state.request_id, release_name=release.name
        )
    finally:
        slots.task_done()
        slots.put_nowait(None)


async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    headers: dict[str, str] = {}
    if exc.code == "unauthorized":
        headers["WWW-Authenticate"] = "Bearer"
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(
        error_body(exc.code, request.state.request_id, exc.retry_after),
        status_code=ERRORS[exc.code][0],
        headers=headers,
    )
