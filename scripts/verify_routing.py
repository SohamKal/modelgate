"""Offline M3 rehearsal through actual HTTP; changes only an explicit *_test database."""

import argparse
import asyncio
import hashlib
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import uvicorn
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.settings import Settings
from app.domain.routing import RoutingConfig, bucket
from app.main import create_app
from app.persistence.models import Invocation, RequestRecord
from scripts.database import repository


async def verify(settings: Settings) -> dict[str, object]:
    if settings.database_url is None or not (
        make_url(settings.database_url.get_secret_value()).database or ""
    ).endswith("_test"):
        raise ValueError("Verification requires an isolated database ending in _test.")
    async with repository(settings) as repo:
        await repo.seed()
        releases = {r.name: r for r in await repo.releases()}
        stable, candidate = releases["fake-stable"], releases["fake-candidate"]
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(settings),
                host="127.0.0.1",
                port=0,
                access_log=False,
                log_config=None,
                log_level="warning",
            )
        )
        task = asyncio.create_task(server.serve())
        results: list[dict[str, object]] = []
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Gateway did not start.")
                    await asyncio.sleep(0.01)
            logging.getLogger("modelgate").setLevel(logging.WARNING)
            port = server.servers[0].sockets[0].getsockname()[1]
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", trust_env=False
            ) as client:
                for mode, percent in [
                    ("stable", 0),
                    ("canary", 0),
                    ("canary", 100),
                    ("canary", 10),
                    ("shadow", 0),
                    ("shadow", 100),
                    ("shadow", 10),
                ]:
                    current = await repo.resolve()
                    config = RoutingConfig.model_validate(
                        {
                            "mode": mode,
                            "stable_release_id": stable.id,
                            "candidate_release_id": candidate.id if mode != "stable" else None,
                            "canary_weight": percent if mode == "canary" else 0,
                            "shadow_sample_rate": percent if mode == "shadow" else 0,
                        }
                    )
                    version = await repo.activate(config, current.version)
                    purpose = "shadow" if mode == "shadow" else "canary"
                    count = sum(
                        bucket(purpose, version, f"case-{i}") < percent * 100 for i in range(10000)
                    )
                    if mode != "stable":
                        assert abs(count / 10000 - percent / 100) <= 0.015
                    ids: list[UUID] = []
                    for i in range(32 if percent == 10 else 2):
                        key = f"case-{i}"
                        result = await client.post(
                            "/v1/chat/completions",
                            headers={
                                "Authorization": "Bearer "
                                + settings.client_api_key.get_secret_value()
                            },
                            json={
                                "messages": [
                                    {"role": "user", "content": "Synthetic routing verification."}
                                ],
                                "request_key": key,
                            },
                        )
                        result.raise_for_status()
                        data = result.json()
                        expected = (
                            "candidate"
                            if mode == "canary" and bucket("canary", version, key) < percent * 100
                            else "stable"
                        )
                        assert (
                            data["serving_role"] == expected and data["config_version"] == version
                        )
                        assert data["recording_status"] == "recorded"
                        ids.append(UUID(data["request_id"]))
                    async with repo.factory() as session:
                        records = (
                            await session.scalars(
                                select(RequestRecord).where(RequestRecord.id.in_(ids))
                            )
                        ).all()
                        invocations = (
                            await session.scalars(
                                select(Invocation).where(Invocation.request_id.in_(ids))
                            )
                        ).all()
                        assert len(records) == len(ids) == len(invocations)
                        assert (
                            all(row.serving_role == "stable" for row in invocations)
                            if mode == "shadow"
                            else True
                        )
                        results.append(
                            {
                                "mode": mode,
                                "percentage": percent,
                                "config_version": version,
                                "allocation_corpus_size": 10000,
                                "selected_keys": count,
                                "http_requests": len(ids),
                                "recorded_invocations": len(invocations),
                                "candidate_serving_calls": sum(
                                    r.serving_role == "candidate" for r in invocations
                                ),
                                "shadow_selected_execution_deferred": sum(
                                    r.shadow_selection == "selected_execution_deferred"
                                    for r in records
                                ),
                                "status": "verified",
                            }
                        )
                assert (await client.get("/health/ready")).status_code == 200
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 5)
    paths = [p for root in ("app", "scripts", "migrations") for p in Path(root).rglob("*.py")]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    return {
        "gate": "M3-routing",
        "status": "verified",
        "verified_at": datetime.now(UTC).isoformat(),
        "source_revision": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
        .decode()
        .strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "python_source_sha256": ":".join(digest.hexdigest()[i : i + 4] for i in range(0, 64, 4)),
        "migration": "a701c3d717e0",
        "stable_release_id": str(stable.id),
        "candidate_release_id": str(candidate.id),
        "real_provider_calls": 0,
        "shadow_execution": "deferred_to_M4",
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = asyncio.run(verify(Settings(stable_release="fake")))  # type: ignore[call-arg]
        rendered = json.dumps(report, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n")
        print(rendered)
        return 0
    except Exception:
        print(
            "Routing verification failed; check the isolated test database "
            "and serving configuration.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
