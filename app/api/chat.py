"""Stable chat serving; release selection is exclusively server configuration."""

import asyncio
import json
import logging
import secrets
import time
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import ERRORS, ErrorResponse, ProviderError, error_body
from app.core.settings import Settings
from app.domain.contracts import ChatRequest, ChatResponse, ProviderResult, Release
from app.domain.routing import decide, private_digest
from app.domain.serving import invoke
from app.persistence.repositories import Repository
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
    if body.max_output_tokens > settings.max_output_tokens:
        raise ProviderError("invalid_request")
    release: Release = request.app.state.release
    repository: Repository | None = request.app.state.repository
    snapshot = None
    decision = None
    role: Literal["stable", "candidate"] = "stable"
    if repository is not None:
        try:
            async with asyncio.timeout(settings.database_deadline_seconds):
                snapshot = await repository.resolve()
            decision = decide(snapshot, body.request_key or request.state.request_id)
            release = decision.release
            if any(
                r.provider not in request.app.state.providers
                for r in [snapshot.stable, *([snapshot.candidate] if snapshot.candidate else [])]
            ):
                raise ValueError("Provider credentials unavailable.")
            role = decision.serving_role
        except Exception:
            raise ProviderError("configuration_unavailable") from None
    if body.temperature is None and release.default_temperature is not None:
        body = body.model_copy(update={"temperature": release.default_temperature})
    if body.temperature is not None and not release.supports_temperature:
        raise ProviderError("invalid_request")
    slots: asyncio.Queue[None] = request.app.state.serving_slots
    try:
        slots.get_nowait()
    except asyncio.QueueEmpty:
        raise ProviderError("serving_busy") from None
    request.state.release_name = release.name
    request.state.serving_role = role
    request.state.config_version = snapshot.version if snapshot else None
    request_values: dict[str, object] = {}
    if snapshot is not None and decision is not None:
        assert settings.content_hash_key is not None and release.id is not None
        secret = settings.content_hash_key.get_secret_value()
        canonical = json.dumps(
            body.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        request_values = {
            "id": UUID(request.state.request_id),
            "config_id": snapshot.id,
            "release_id": release.id,
            "serving_role": role,
            "content_hash": private_digest(secret, "content", canonical),
            "routing_key_digest": private_digest(
                secret, "routing-key", body.request_key or request.state.request_id
            ),
            "canary_bucket": decision.canary_bucket,
            "shadow_bucket": decision.shadow_bucket,
            "shadow_selection": decision.shadow_selection,
            "received_at": datetime.now(UTC),
        }
    started_at = datetime.now(UTC)
    start = time.perf_counter()

    async def record(result: ProviderResult | None, status: str, error: str | None) -> bool:
        if repository is None:
            return True
        usage = result.usage if result else None
        values: dict[str, object] = {
            "request_id": UUID(request.state.request_id),
            "release_id": release.id,
            "serving_role": role,
            "status": status,
            "max_output_tokens": body.max_output_tokens,
            "temperature": body.temperature,
            "latency_ms": round((time.perf_counter() - start) * 1000, 3),
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "finish_reason": result.finish_reason if result else None,
            "error_code": error,
            "started_at": started_at,
            "completed_at": datetime.now(UTC),
        }
        try:
            async with asyncio.timeout(settings.database_deadline_seconds):
                await repository.record_outcome(request_values, values)
            request.state.recording_status = "recorded"
            return True
        except Exception:
            request.state.recording_status = "degraded"
            logging.getLogger("modelgate").warning(
                "recording_degraded",
                extra={
                    "request_id": request.state.request_id,
                    "config_version": snapshot.version if snapshot else None,
                },
            )
            return False

    try:
        if repository is not None:
            try:
                async with asyncio.timeout(settings.database_deadline_seconds):
                    await repository.record_request(request_values)
            except Exception:
                logging.getLogger("modelgate").warning(
                    "recording_degraded", extra={"request_id": request.state.request_id}
                )
        # Provider duration excludes preliminary and final recording latency.
        start = time.perf_counter()
        started_at = datetime.now(UTC)
        provider: Provider = request.app.state.provider
        if repository is not None:
            provider = (
                request.app.state.provider_override or request.app.state.providers[release.provider]
            )
        result = await invoke(provider, body, release, settings.serving_deadline_seconds)
        recorded = await record(result, "success", None)
        return ChatResponse(
            **result.model_dump(),
            request_id=request.state.request_id,
            release_name=release.name,
            serving_role=role,
            config_version=snapshot.version if snapshot else None,
            recording_status=("recorded" if recorded else "degraded")
            if repository
            else "not_applicable",
        )
    except asyncio.CancelledError:
        await record(None, "cancelled", None)
        raise
    except ProviderError as exc:
        await record(None, "failed", exc.code)
        raise
    except Exception:
        await record(None, "failed", "internal_error")
        raise
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
