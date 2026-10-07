"""Trusted local CLI; HTTP administration and promotion remain M7 work."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.settings import Settings
from app.domain.contracts import Release
from app.domain.routing import RoutingConfig
from scripts.database import repository


async def run(args: argparse.Namespace) -> None:
    settings = Settings(stable_release="fake")  # type: ignore[call-arg]
    async with repository(settings) as repo:
        if args.action == "register":
            release = Release.model_validate_json(args.file.read_text())
            if release.id is not None:
                raise ValueError("Release IDs are server assigned.")
            registered = await repo.register(release)
            print(registered.model_dump_json())
        elif args.action == "history":
            print(json.dumps(await repo.history(), indent=2))
        elif args.action == "releases":
            print(json.dumps([r.model_dump(mode="json") for r in await repo.releases()], indent=2))
        else:
            releases = {r.name: r for r in await repo.releases()}
            stable = releases[args.stable]
            candidate = releases[args.candidate] if args.candidate else None
            for release in [stable, *([candidate] if candidate else [])]:
                key = {
                    "fake": None,
                    "groq": settings.groq_api_key,
                    "openai": settings.openai_api_key,
                }[release.provider]
                if release.provider != "fake" and (
                    key is None or not key.get_secret_value().strip()
                ):
                    raise ValueError("Selected provider credentials missing.")
            config = RoutingConfig.model_validate(
                {
                    "mode": args.mode,
                    "stable_release_id": stable.id,
                    "candidate_release_id": candidate.id if candidate else None,
                    "canary_weight": args.canary_weight,
                    "shadow_sample_rate": args.shadow_sample_rate,
                }
            )
            version = await repo.activate(config, args.expected_version)
            print(json.dumps({"active_version": version, "mode": config.mode}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("history")
    commands.add_parser("releases")
    register = commands.add_parser("register")
    register.add_argument("file", type=Path)
    activate = commands.add_parser("activate")
    activate.add_argument("--mode", choices=["stable", "canary", "shadow"], required=True)
    activate.add_argument("--stable", required=True)
    activate.add_argument("--candidate")
    activate.add_argument("--canary-weight", type=int, default=0)
    activate.add_argument("--shadow-sample-rate", type=int, default=0)
    activate.add_argument("--expected-version", type=int, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
        return 0
    except Exception:
        print(
            "Configuration change failed; check inputs, credentials and the current version. "
            "Active history was preserved.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
