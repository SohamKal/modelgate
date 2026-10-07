import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.contracts import ChatRequest, Release
from app.domain.routing import RoutingConfig, ShadowPayload, Snapshot, bucket, decide


def snapshot(mode: str = "stable", canary: int = 0, shadow: int = 0) -> Snapshot:
    stable = Release(
        id=uuid4(), name="stable", provider="fake", model="stable-v1", supports_temperature=True
    )
    candidate = Release(
        id=uuid4(),
        name="candidate",
        provider="fake",
        model="candidate-v1",
        supports_temperature=True,
    )
    return Snapshot(
        id=uuid4(),
        version=1,
        stable=stable,
        candidate=candidate,
        config=RoutingConfig.model_validate(
            {
                "mode": mode,
                "stable_release_id": stable.id,
                "candidate_release_id": candidate.id,
                "canary_weight": canary,
                "shadow_sample_rate": shadow,
            }
        ),
    )


@pytest.mark.parametrize("weight,role", [(0, "stable"), (100, "candidate")])
def test_canary_boundaries(weight: int, role: str) -> None:
    for key in ["a", "", "unicode-你好", "demo-case-1"]:
        assert decide(snapshot("canary", weight), key).serving_role == role


def test_cross_process_determinism_and_distribution() -> None:
    assert bucket("canary", 1, "demo-case-1") == 8396
    assert bucket("shadow", 1, "demo-case-1") == 5053
    result = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from app.domain.routing import bucket; print(bucket('canary', 1, 'demo-case-1'))",
        ]
    )
    assert int(result) == bucket("canary", 1, "demo-case-1")
    for purpose in ("canary", "shadow"):
        selected = sum(bucket(purpose, 1, f"case-{i}") < 1000 for i in range(10000))
        assert abs(selected / 10000 - 0.1) <= 0.015
    assert bucket("canary", 1, "demo-case-1") != bucket("shadow", 1, "demo-case-1")
    assert bucket("canary", 1, "demo-case-1") != bucket("canary", 2, "demo-case-1")


@pytest.mark.parametrize("value,role", [(999, "candidate"), (1000, "stable")])
def test_threshold_is_exclusive(monkeypatch: pytest.MonkeyPatch, value: int, role: str) -> None:
    monkeypatch.setattr("app.domain.routing.bucket", lambda purpose, version, key: value)
    assert decide(snapshot("canary", 10), "key").serving_role == role


@pytest.mark.parametrize(
    "rate,selection", [(0, "not_selected"), (100, "selected_execution_deferred")]
)
def test_shadow_always_serves_stable(rate: int, selection: str) -> None:
    for i in range(30):
        choice = decide(snapshot("shadow", shadow=rate), str(i))
        assert choice.serving_role == "stable" and choice.shadow_selection == selection


@pytest.mark.parametrize(
    "changes",
    [
        {"canary_weight": 101},
        {"canary_weight": -1},
        {"mode": "stable", "canary_weight": 10},
        {"mode": "canary", "candidate_release_id": None},
        {"mode": "shadow", "shadow_sample_rate": 50, "canary_weight": 1},
    ],
)
def test_invalid_configuration(changes: dict[str, object]) -> None:
    config = snapshot().config.model_dump() | changes
    with pytest.raises(ValidationError):
        RoutingConfig.model_validate(config)


def test_payload_is_immutable_and_bounded() -> None:
    request = ChatRequest.model_validate({"messages": [{"role": "user", "content": "original"}]})
    snap = snapshot("shadow", shadow=100)
    job = ShadowPayload.build("request", snap, request, datetime.now(UTC), 131072)
    request.messages.clear()
    assert "original" in job.request_json and job.snapshot.version == 1
    with pytest.raises(ValueError):
        ShadowPayload.build("request", snap, request, datetime.now(UTC), 10)
