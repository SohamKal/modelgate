"""Application factory; provider resources belong to application lifespan."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.api.chat import provider_error_handler, router
from app.core.boundary import RequestBoundaryMiddleware
from app.core.errors import ProviderError, error_body
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.persistence.repositories import Repository
from app.persistence.session import create_engine, sessions
from app.providers.base import Provider
from app.providers.fake import FakeProvider
from app.providers.groq import GroqProvider
from app.providers.openai import OpenAIProvider


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    provider: Provider | None = None,
    ephemeral: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Normal serving ignores the legacy adapter-verification selector.
        configuration = settings or Settings(stable_release="fake")  # type: ignore[call-arg]
        release = configuration.active_release()
        configure_logging()
        engine = None
        if not ephemeral:
            if (
                configuration.content_hash_key is None
                or len(configuration.content_hash_key.get_secret_value()) < 16
            ):
                raise ValueError("MODELGATE_CONTENT_HASH_KEY must contain at least 16 characters.")
            engine = create_engine(configuration)
        application.state.repository = Repository(sessions(engine)) if engine is not None else None
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                configuration.serving_deadline_seconds,
                connect=min(2, configuration.serving_deadline_seconds),
            ),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=configuration.serving_concurrency),
        ) as client:
            application.state.settings = configuration
            application.state.release = release
            application.state.http_client = client
            registry: dict[str, Provider] = {"fake": FakeProvider()}
            if configuration.groq_api_key and configuration.groq_api_key.get_secret_value().strip():
                registry["groq"] = GroqProvider(
                    client, configuration.groq_api_key.get_secret_value()
                )
            if (
                configuration.openai_api_key
                and configuration.openai_api_key.get_secret_value().strip()
            ):
                registry["openai"] = OpenAIProvider(
                    client, configuration.openai_api_key.get_secret_value()
                )
            application.state.providers = registry
            application.state.provider_override = provider
            if provider is not None:
                application.state.provider = provider
            elif release.provider == "fake":
                application.state.provider = FakeProvider()
            elif release.provider == "groq":
                assert configuration.groq_api_key is not None
                application.state.provider = GroqProvider(
                    client, configuration.groq_api_key.get_secret_value()
                )
            else:
                assert configuration.openai_api_key is not None
                application.state.provider = OpenAIProvider(
                    client, configuration.openai_api_key.get_secret_value()
                )
            slots: asyncio.Queue[None] = asyncio.Queue(configuration.serving_concurrency)
            for _ in range(configuration.serving_concurrency):
                slots.put_nowait(None)
            application.state.serving_slots = slots
            application.state.ready = True
            try:
                yield
            finally:
                application.state.ready = False
                if engine is not None:
                    await engine.dispose()

    application = FastAPI(title="Modelgate", version="0.1.0", lifespan=lifespan)
    application.add_middleware(RequestBoundaryMiddleware, state=application.state)
    application.include_router(router)
    application.mount("/metrics", make_asgi_app())
    application.add_exception_handler(ProviderError, provider_error_handler)  # type: ignore[arg-type]

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's default details echo invalid input, including submitted prompt bodies.
        return JSONResponse(
            error_body("invalid_request", request.state.request_id), status_code=422
        )

    @application.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready")
    async def readiness() -> JSONResponse:
        ready = getattr(application.state, "ready", False)
        repository = getattr(application.state, "repository", None)
        if ready and repository is not None:
            try:
                async with asyncio.timeout(application.state.settings.database_deadline_seconds):
                    snapshot = await repository.resolve()
                    releases = [snapshot.stable]
                    if snapshot.candidate is not None:
                        releases.append(snapshot.candidate)
                    ready = all(r.provider in application.state.providers for r in releases)
            except Exception:
                ready = False
        return JSONResponse(
            {"status": "ready" if ready else "not_ready"}, status_code=200 if ready else 503
        )

    return application


app = create_app()
