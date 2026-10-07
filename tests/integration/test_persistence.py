"""Real PostgreSQL evidence; all cleanup is confined to an explicit *_test database."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.errors import ProviderError
from app.core.settings import Settings
from app.domain.contracts import ChatRequest, ProviderResult, Release
from app.domain.routing import RoutingConfig
from app.main import create_app
from app.persistence.models import (
    ActivationEvent,
    ActiveConfig,
    Invocation,
    ModelRelease,
    RequestRecord,
    RoutingVersion,
)
from app.persistence.repositories import ConfigurationConflict, Repository
from app.persistence.session import create_engine, sessions
from app.providers.base import Provider


@pytest.fixture
async def database(
    settings: Settings, postgres_url: str
) -> AsyncIterator[tuple[Settings, Repository]]:
    settings = settings.model_copy(
        update={
            "database_url": SecretStr(postgres_url),
            "content_hash_key": SecretStr("synthetic.hash.credential"),
            "database_deadline_seconds": 0.5,
        }
    )
    engine = create_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE invocations, requests, activation_events, active_config, "
                    "routing_configs, model_releases RESTART IDENTITY"
                )
            )
            await connection.execute(
                text("INSERT INTO active_config (singleton, config_id) VALUES (1, NULL)")
            )
        repo = Repository(sessions(engine))
        await repo.seed()
        yield settings, repo
    finally:
        await engine.dispose()


@asynccontextmanager
async def api(
    settings: Settings,
    provider: Provider | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    app = create_app(settings, provider=provider, transport=transport)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        yield app, client


@asynccontextmanager
async def reject_inserts(repo: Repository, table: str) -> AsyncIterator[None]:
    assert table in {"requests", "invocations", "activation_events"}
    async with repo.factory.begin() as session:
        await session.execute(
            text(
                "CREATE FUNCTION m3_test_deny() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'test write outage'; END; $$ LANGUAGE plpgsql"
            )
        )
        await session.execute(
            text(
                f"CREATE TRIGGER m3_test_deny BEFORE INSERT ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION m3_test_deny()"
            )
        )
    try:
        yield
    finally:
        async with repo.factory.begin() as session:
            await session.execute(text(f"DROP TRIGGER m3_test_deny ON {table}"))
            await session.execute(text("DROP FUNCTION m3_test_deny()"))


async def configure(repo: Repository, mode: str, percentage: int = 0) -> int:
    snapshot = await repo.resolve()
    candidate = next(r for r in await repo.releases() if r.name == "fake-candidate")
    config = RoutingConfig.model_validate(
        {
            "mode": mode,
            "stable_release_id": snapshot.stable.id,
            "candidate_release_id": candidate.id if mode != "stable" else None,
            "canary_weight": percentage if mode == "canary" else 0,
            "shadow_sample_rate": percentage if mode == "shadow" else 0,
        }
    )
    return await repo.activate(config, snapshot.version)


async def test_seed_history_constraints_and_immutability(
    database: tuple[Settings, Repository],
) -> None:
    _, repo = database
    first = await repo.resolve()
    assert await repo.seed() == first.version
    version = await configure(repo, "canary", 10)
    assert await repo.seed() == version
    assert len(await repo.history()) == 2
    with pytest.raises(ConfigurationConflict):
        await repo.register(first.stable.model_copy(update={"model": "changed"}))
    for cls, values in [
        (ModelRelease, {"model": "changed"}),
        (RoutingVersion, {"canary_weight": 30}),
        (ActivationEvent, {"actor": "changed"}),
    ]:
        with pytest.raises(DBAPIError):
            async with repo.factory.begin() as session:
                await session.execute(update(cls).values(**values))
    with pytest.raises(IntegrityError):
        async with repo.factory.begin() as session:
            session.add(
                RoutingVersion(
                    mode="canary",
                    stable_release_id=first.stable.id,
                    candidate_release_id=None,
                    canary_weight=101,
                    shadow_sample_rate=0,
                )
            )
    assert (await repo.resolve()).version == version


async def test_activation_failure_and_stale_concurrency(
    database: tuple[Settings, Repository],
) -> None:
    _, repo = database
    first = await repo.resolve()
    async with reject_inserts(repo, "activation_events"):
        with pytest.raises(DBAPIError):
            await configure(repo, "canary", 10)
    assert (await repo.resolve()).version == first.version
    assert len(await repo.history()) == 1
    config = first.config
    results = await asyncio.gather(
        repo.activate(config, first.version),
        repo.activate(config, first.version),
        return_exceptions=True,
    )
    assert sum(isinstance(r, int) for r in results) == 1
    assert sum(isinstance(r, ConfigurationConflict) for r in results) == 1
    async with repo.factory() as session:
        assert await session.scalar(select(func.count()).select_from(ActivationEvent)) == 2


@pytest.mark.parametrize(
    "mode,percentage,role,selection",
    [
        ("stable", 0, "stable", "not_applicable"),
        ("canary", 0, "stable", "not_applicable"),
        ("canary", 100, "candidate", "not_applicable"),
        ("shadow", 0, "stable", "not_selected"),
        ("shadow", 100, "stable", "selected_execution_deferred"),
    ],
)
async def test_persisted_api_paths(
    database: tuple[Settings, Repository],
    headers: dict[str, str],
    mode: str,
    percentage: int,
    role: str,
    selection: str,
) -> None:
    settings, repo = database
    version = await configure(repo, mode, percentage)
    calls: list[Release] = []

    class CountingProvider:
        async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
            calls.append(release)
            return ProviderResult(
                content="synthetic output", model=release.model, finish_reason="stop"
            )

    private = "private.request.marker"
    payload = {
        "messages": [{"role": "user", "content": private}],
        "request_key": "private.routing.marker",
        "task_type": "private.task.marker",
    }
    async with api(settings, CountingProvider()) as (app, client):
        assert (await client.get("/health/ready")).status_code == 200
        first = await client.post("/v1/chat/completions", headers=headers, json=payload)
        second = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert first.status_code == 200 and second.status_code == 200
        result = first.json()
        assert result["config_version"] == version and result["serving_role"] == role
        assert result["recording_status"] == "recorded" and result["usage"] is None
        assert len(calls) == 2 and calls[0] == calls[1]
        engine = app.state.repository.factory.kw["bind"]
    assert not app.state.ready
    async with repo.factory() as session:
        row = await session.get(RequestRecord, UUID(result["request_id"]))
        assert row is not None and row.shadow_selection == selection
        invocation = (
            await session.execute(select(Invocation).where(Invocation.request_id == row.id))
        ).scalar_one()
        assert invocation.release_id == row.release_id and invocation.status == "success"
        assert invocation.serving_role == role and invocation.input_tokens is None
        metadata = {c.name: str(getattr(row, c.name)) for c in row.__table__.columns}
        assert "private" not in json.dumps(metadata)
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("table", ["requests", "invocations"])
async def test_success_survives_recording_outage(
    database: tuple[Settings, Repository],
    headers: dict[str, str],
    payload: dict[str, Any],
    table: str,
) -> None:
    settings, repo = database
    async with api(settings) as (_, client), reject_inserts(repo, table):
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert result.status_code == 200 and result.json()["recording_status"] == "degraded"
    async with repo.factory() as session:
        assert await session.scalar(select(func.count()).select_from(Invocation)) == 0


async def test_preliminary_recording_failure_is_repaired(
    database: tuple[Settings, Repository],
    headers: dict[str, str],
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, repo = database
    async with api(settings) as (app, client):

        async def fail(values: dict[str, object]) -> None:
            async with repo.factory() as session:
                await session.execute(text("SELECT 1 / 0"))

        monkeypatch.setattr(app.state.repository, "record_request", fail)
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert result.status_code == 200 and result.json()["recording_status"] == "recorded"
    async with repo.factory() as session:
        assert await session.scalar(select(func.count()).select_from(Invocation)) == 1


async def test_read_failure_and_missing_config_fail_closed(
    database: tuple[Settings, Repository],
    headers: dict[str, str],
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, repo = database

    class NeverProvider:
        async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
            pytest.fail("Config read failure must not invoke a provider.")

    async with api(settings, NeverProvider()) as (app, client):

        async def fail() -> None:
            async with repo.factory() as session:
                await session.execute(text("SELECT 1 / 0"))

        monkeypatch.setattr(app.state.repository, "resolve", fail)
        assert (await client.get("/health/ready")).status_code == 503
        assert (await client.get("/health/live")).status_code == 200
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert (
            result.status_code == 503
            and result.json()["error"]["code"] == "configuration_unavailable"
        )
    async with repo.factory.begin() as session:
        await session.execute(update(ActiveConfig).values(config_id=None))
    async with api(settings, NeverProvider()) as (_, client):
        assert (
            await client.post("/v1/chat/completions", headers=headers, json=payload)
        ).status_code == 503


async def test_snapshot_pinned_during_activation(
    database: tuple[Settings, Repository], headers: dict[str, str], payload: dict[str, Any]
) -> None:
    settings, repo = database
    original = await repo.resolve()
    started, finish = asyncio.Event(), asyncio.Event()

    class BlockingProvider:
        async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
            started.set()
            await finish.wait()
            return ProviderResult(content="ok", model=release.model)

    async with api(settings, BlockingProvider()) as (_, client):
        task = asyncio.create_task(
            client.post("/v1/chat/completions", headers=headers, json=payload)
        )
        await asyncio.wait_for(started.wait(), 1)
        version = await configure(repo, "canary", 100)
        finish.set()
        result = await asyncio.wait_for(task, 2)
        assert result.json()["config_version"] == original.version
        assert result.json()["release_name"] == "fake-stable"
        next_result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert next_result.json()["config_version"] == version
        assert next_result.json()["release_name"] == "fake-candidate"


async def test_candidate_error_preserved_during_recording_failure(
    database: tuple[Settings, Repository], headers: dict[str, str], payload: dict[str, Any]
) -> None:
    settings, repo = database
    await configure(repo, "canary", 100)
    calls = 0

    class FailingProvider:
        async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
            nonlocal calls
            calls += 1
            raise ProviderError("provider_rate_limited", retry_after=3)

    async with api(settings, FailingProvider()) as (_, client), reject_inserts(repo, "invocations"):
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert result.status_code == 429 and result.headers["retry-after"] == "3"
        assert calls == 1


async def test_db_deadline_and_cancellation_cleanup(
    database: tuple[Settings, Repository],
    headers: dict[str, str],
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, repo = database
    async with api(settings) as (app, client):

        async def stall() -> None:
            async with repo.factory() as session:
                await session.execute(text("SELECT pg_sleep(10)"))

        monkeypatch.setattr(app.state.repository, "resolve", stall)
        before = asyncio.get_running_loop().time()
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert result.status_code == 503
        assert asyncio.get_running_loop().time() - before < 1.5
    started = asyncio.Event()

    class BlockingProvider:
        async def complete(self, request: ChatRequest, release: Release) -> ProviderResult:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async with api(settings, BlockingProvider()) as (app, client):
        task = asyncio.create_task(
            client.post("/v1/chat/completions", headers=headers, json=payload)
        )
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert app.state.serving_slots.qsize() == settings.serving_concurrency
    async with repo.factory() as session:
        invocation = (await session.scalars(select(Invocation))).one()
        assert invocation.status == "cancelled"


async def test_missing_key_uses_ingress_id_and_usage_is_stored(
    database: tuple[Settings, Repository], headers: dict[str, str], payload: dict[str, Any]
) -> None:
    from app.domain.routing import bucket

    settings, repo = database
    version = await configure(repo, "canary", 10)
    async with api(settings) as (_, client):
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert result.status_code == 200
    async with repo.factory() as session:
        row = await session.get(RequestRecord, UUID(result.json()["request_id"]))
        assert row is not None and row.canary_bucket == bucket("canary", version, str(row.id))
        invocation = (await session.scalars(select(Invocation))).one()
        assert invocation.total_tokens == result.json()["usage"]["total_tokens"]


@pytest.mark.parametrize("provider_name", ["openai", "groq"])
async def test_registered_real_release_uses_registry_offline(
    database: tuple[Settings, Repository],
    headers: dict[str, str],
    payload: dict[str, Any],
    openai_response: dict[str, Any],
    provider_name: str,
) -> None:
    settings, repo = database
    release = await repo.register(
        Release.model_validate(
            {
                "name": "new-real-release",
                "provider": provider_name,
                "model": "synthetic-model",
                "supports_temperature": False,
            }
        )
    )
    original = await repo.resolve()
    assert release.id is not None
    await repo.activate(RoutingConfig(stable_release_id=release.id), original.version)
    settings = settings.model_copy(
        update={f"{provider_name}_api_key": SecretStr("synthetic.provider.credential")}
    )
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert json.loads(request.content)["model"] == "synthetic-model"
        return httpx.Response(200, json=openai_response | {"model": "synthetic-model"})

    async with api(settings, transport=httpx.MockTransport(handle)) as (_, client):
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert result.status_code == 200 and result.json()["release_name"] == "new-real-release"
        rejected = await client.post(
            "/v1/chat/completions", headers=headers, json=payload | {"temperature": 0}
        )
        assert rejected.status_code == 422 and calls == 1


async def test_unavailable_database_readiness_and_lifecycle(
    settings: Settings, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    settings = settings.model_copy(
        update={
            "database_url": SecretStr("postgresql+asyncpg://test@127.0.0.1:1/unavailable_test"),
            "content_hash_key": SecretStr("synthetic.hash.credential"),
            "database_deadline_seconds": 0.1,
        }
    )
    async with api(settings) as (app, client):
        assert (await client.get("/health/ready")).status_code == 503
        assert (await client.get("/health/live")).status_code == 200
        result = await client.post("/v1/chat/completions", headers=headers, json=payload)
        assert result.status_code == 503
    assert not app.state.ready and app.state.http_client.is_closed


async def test_normal_startup_ignores_legacy_selector(
    database: tuple[Settings, Repository],
    headers: dict[str, str],
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, _ = database
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MODELGATE_CLIENT_API_KEY", settings.client_api_key.get_secret_value())
    monkeypatch.setenv("MODELGATE_CONTENT_HASH_KEY", settings.content_hash_key.get_secret_value())
    monkeypatch.setenv("DATABASE_URL", settings.database_url.get_secret_value())
    monkeypatch.setenv("MODELGATE_STABLE_RELEASE", "openai-a")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        response = await client.post(
            "/v1/chat/completions",
            headers=headers,
            json={"messages": [{"role": "user", "content": "Synthetic startup check."}]},
        )
        assert response.status_code == 200 and response.json()["release_name"] == "fake-stable"
