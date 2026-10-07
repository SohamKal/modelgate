from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.settings import Settings
from scripts.trace_spike import retrieve_trace
from scripts.verify_models import verify


async def test_live_command_exercises_both_gateway_configurations_offline(
    settings: Settings, openai_response: dict[str, Any]
) -> None:
    configuration = Settings.model_validate(
        settings.model_dump()
        | {
            "openai_model_a": "model-a",
            "openai_model_b": "model-b",
            "openai_api_key": SecretStr("synthetic-upstream-credential"),
        }
    )
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        model = json.loads(request.content)["model"]
        seen.append(model)
        return httpx.Response(200, json=openai_response | {"model": model})

    results = await verify(configuration, httpx.MockTransport(handle))
    assert seen == ["model-a", "model-b"]
    assert all(result["status"] == "verified" for result in results)


async def test_live_command_validates_both_before_calling(settings: Settings) -> None:
    def never(request: httpx.Request) -> httpx.Response:
        pytest.fail("Missing configuration must not cause an upstream call.")

    with pytest.raises(ValidationError):
        await verify(settings, httpx.MockTransport(never))


async def test_trace_gate_requires_matching_jaeger_span() -> None:
    trace_id = "0" * 31 + "1"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": [
                    {
                        "spans": [
                            {
                                "operationName": "m2.trace_export",
                                "traceID": trace_id,
                            }
                        ]
                    }
                ]
            },
        )
    )
    assert await retrieve_trace(trace_id, "http://jaeger", transport=transport)
    missing = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    assert not await retrieve_trace(trace_id, "http://jaeger", seconds=0.01, transport=missing)
