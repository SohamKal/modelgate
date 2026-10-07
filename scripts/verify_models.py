"""Explicit live gate: one synthetic request through the gateway per model."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.core.settings import MissingProviderSettings, Settings
from app.domain.contracts import ChatResponse
from app.main import create_app


def model_configurations(settings: Settings, provider: str | None = None) -> list[Settings]:
    """Validate both configurations before making either paid call."""
    selected = provider or settings.verification_provider
    if selected not in {"openai", "groq"}:
        raise ValueError("Verification provider must be openai or groq.")
    return [
        Settings.model_validate(settings.model_dump() | {"stable_release": name})
        for name in (f"{selected}-a", f"{selected}-b")
    ]


def configuration_problems(exc: ValidationError) -> list[str]:
    """Report known field names and fixed messages without echoing invalid inputs."""
    aliases = {
        "client_api_key": "MODELGATE_CLIENT_API_KEY",  # pragma: allowlist secret (setting name)
        "openai_api_key": "OPENAI_API_KEY",  # pragma: allowlist secret (setting name)
        "openai_model_a": "OPENAI_MODEL_A",
        "openai_model_b": "OPENAI_MODEL_B",
        "groq_api_key": "GROQ_API_KEY",  # pragma: allowlist secret (setting name)
        "groq_model_a": "GROQ_MODEL_A",
        "groq_model_b": "GROQ_MODEL_B",
    }
    root_messages = {
        "Gateway and provider credentials must be different.",
        "Use distinct model identifiers for the two OpenAI configurations.",
        "Use distinct model identifiers for the two Groq configurations.",
    }
    problems: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        cause = error.get("ctx", {}).get("error")
        if isinstance(cause, MissingProviderSettings):
            problems.extend(f"{name} is empty or missing." for name in cause.names)
        elif error["loc"]:
            field = str(error["loc"][0])
            label = aliases.get(field, field if field.isupper() else "MODELGATE_" + field.upper())
            problems.append(f"{label} is missing or invalid.")
        elif isinstance(cause, ValueError) and str(cause) in root_messages:
            problems.append(str(cause))
        else:
            problems.append("Local gateway configuration is invalid; check .env settings.")
    return list(dict.fromkeys(problems))


async def verify(
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    *,
    provider: str | None = None,
) -> list[dict[str, object]]:
    configurations = model_configurations(settings, provider)
    results: list[dict[str, object]] = []
    for configuration in configurations:
        app = create_app(configuration, transport=transport, ephemeral=True)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client,
        ):
            response = await client.post(
                "/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {configuration.client_api_key.get_secret_value()}"
                },
                json={
                    "messages": [{"role": "user", "content": "Reply with the word OK."}],
                    "max_output_tokens": min(
                        512 if configuration.active_release().provider == "groq" else 200,
                        configuration.max_output_tokens,
                    ),
                },
            )
        if response.status_code == 200:
            normalized = ChatResponse.model_validate(response.json())
            valid = (
                bool(normalized.content.strip())
                and normalized.release_name == configuration.stable_release
                and normalized.serving_role == "stable"
                and (
                    configuration.active_release().provider != "groq"
                    or normalized.model == configuration.active_release().model
                )
                and normalized.finish_reason == "stop"
            )
            results.append(
                {
                    "release": configuration.stable_release,
                    "provider": configuration.active_release().provider,
                    "model": normalized.model,
                    "requested_model": configuration.active_release().model,
                    "request_id": normalized.request_id,
                    "status": "verified" if valid else "pending",
                    "finish_reason": normalized.finish_reason,
                    "usage": normalized.usage.model_dump() if normalized.usage else None,
                    "serving_role": normalized.serving_role,
                }
            )
        else:
            results.append(
                {
                    "release": configuration.stable_release,
                    "provider": configuration.active_release().provider,
                    "status": "pending",
                    "error_code": response.json()["error"]["code"],
                }
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--provider",
        choices=("openai", "groq"),
        help="Provider to verify; defaults to MODELGATE_VERIFICATION_PROVIDER.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate local settings without sending requests or writing evidence.",
    )
    args = parser.parse_args()
    try:
        settings = Settings()  # type: ignore[call-arg]  # Environment supplies required keys.
        selected = args.provider or settings.verification_provider
        model_configurations(settings, selected)
    except ValidationError as exc:
        print("Live gate pending: local configuration check failed.", file=sys.stderr)
        for problem in configuration_problems(exc):
            print(f"- {problem}", file=sys.stderr)
        print(
            "No model requests were sent. For free offline verification, run "
            "uv run python -m scripts.smoke_gateway.",
            file=sys.stderr,
        )
        return 2
    if args.check_config:
        print(json.dumps({"status": "configured", "live_requests_sent": 0}))
        return 0
    try:
        results = asyncio.run(verify(settings, provider=selected))
    except ValidationError:
        print("Live gate pending: an invalid gateway response was returned.", file=sys.stderr)
        return 2
    report = {
        "gate": "M2.6-live",
        "provider": selected,
        "status": "verified" if all(r["status"] == "verified" for r in results) else "pending",
        "verified_at": datetime.now(UTC).isoformat(),
        "results": results,
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n")
    return 0 if all(result["status"] == "verified" for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
