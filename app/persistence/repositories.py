"""Short transactions; configuration changes commit before they become observable."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.contracts import Release
from app.domain.routing import RoutingConfig, Snapshot
from app.persistence.models import (
    ActivationEvent,
    ActiveConfig,
    Invocation,
    ModelRelease,
    RequestRecord,
    RoutingVersion,
)


def release_value(row: ModelRelease) -> Release:
    return Release.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "provider": row.provider,
            "model": row.model,
            "supports_temperature": row.supports_temperature,
            "default_temperature": row.default_temperature,
        }
    )


class ConfigurationConflict(ValueError):
    pass


class Repository:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def register(self, release: Release) -> Release:
        if release.default_temperature is not None and not release.supports_temperature:
            raise ValueError("Unsupported temperature default.")
        values = release.model_dump(exclude={"id"})
        async with self.factory.begin() as session:
            await session.execute(
                insert(ModelRelease)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["name"])
            )
            row = (
                await session.execute(select(ModelRelease).where(ModelRelease.name == release.name))
            ).scalar_one()
            actual = release_value(row)
            if actual.model_dump(exclude={"id"}) != values:
                raise ConfigurationConflict(
                    "Release name already has a different immutable definition."
                )
            return actual

    async def releases(self) -> list[Release]:
        async with self.factory() as session:
            return [
                release_value(row)
                for row in (
                    await session.scalars(select(ModelRelease).order_by(ModelRelease.name))
                ).all()
            ]

    async def resolve(self) -> Snapshot:
        async with self.factory() as session:
            # Only the pointer changes; its immutable references pin history after one read.
            config_id = (
                await session.execute(
                    select(ActiveConfig.config_id).where(ActiveConfig.singleton == 1)
                )
            ).scalar_one_or_none()
            if config_id is None:
                raise ValueError("No active configuration.")
            row = await session.get(RoutingVersion, config_id)
            assert row is not None
            stable = await session.get(ModelRelease, row.stable_release_id)
            candidate = (
                await session.get(ModelRelease, row.candidate_release_id)
                if row.candidate_release_id
                else None
            )
            assert stable is not None
            config = RoutingConfig.model_validate(
                {
                    "mode": row.mode,
                    "stable_release_id": row.stable_release_id,
                    "candidate_release_id": row.candidate_release_id,
                    "canary_weight": row.canary_weight,
                    "shadow_sample_rate": row.shadow_sample_rate,
                }
            )
            return Snapshot(
                id=row.id,
                version=row.version,
                config=config,
                stable=release_value(stable),
                candidate=release_value(candidate) if candidate else None,
            )

    async def activate(self, config: RoutingConfig, expected_version: int | None) -> int:
        async with self.factory.begin() as session:
            pointer = (
                await session.execute(
                    select(ActiveConfig).where(ActiveConfig.singleton == 1).with_for_update()
                )
            ).scalar_one()
            old = (
                await session.get(RoutingVersion, pointer.config_id) if pointer.config_id else None
            )
            if (old.version if old else None) != expected_version:
                raise ConfigurationConflict(
                    "Active configuration changed; inspect and retry explicitly."
                )
            row = RoutingVersion(**config.model_dump())
            session.add(row)
            await session.flush()
            session.add(ActivationEvent(previous_config_id=pointer.config_id, config_id=row.id))
            pointer.config_id = row.id
            return row.version

    async def history(self) -> list[dict[str, object]]:
        async with self.factory() as session:
            active = (await session.execute(select(ActiveConfig.config_id))).scalar_one()
            rows = (
                await session.scalars(select(RoutingVersion).order_by(RoutingVersion.version))
            ).all()
            return [
                {
                    "version": r.version,
                    "mode": r.mode,
                    "active": r.id == active,
                    "stable_release_id": str(r.stable_release_id),
                    "candidate_release_id": str(r.candidate_release_id)
                    if r.candidate_release_id
                    else None,
                    "canary_weight": r.canary_weight,
                    "shadow_sample_rate": r.shadow_sample_rate,
                }
                for r in rows
            ]

    async def record_request(self, values: dict[str, object]) -> None:
        async with self.factory.begin() as session:
            await session.execute(
                insert(RequestRecord).values(**values).on_conflict_do_nothing(index_elements=["id"])
            )

    async def record_outcome(
        self, request_values: dict[str, object], values: dict[str, object]
    ) -> None:
        async with self.factory.begin() as session:
            await session.execute(
                insert(RequestRecord)
                .values(**request_values)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await session.execute(
                insert(Invocation)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["request_id", "release_id", "serving_role"])
            )

    async def seed(self) -> int:
        stable = await self.register(
            Release(
                name="fake-stable",
                provider="fake",
                model="fake-stable-v1",
                supports_temperature=True,
            )
        )
        await self.register(
            Release(
                name="fake-candidate",
                provider="fake",
                model="fake-candidate-v1",
                supports_temperature=True,
            )
        )
        try:
            return (await self.resolve()).version
        except ValueError:
            assert stable.id is not None
            try:
                return await self.activate(RoutingConfig(stable_release_id=stable.id), None)
            except ConfigurationConflict:
                return (await self.resolve()).version
