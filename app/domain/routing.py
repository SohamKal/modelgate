"""Pure routing with explicit encoding and purpose-separated hashes."""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.contracts import ChatRequest, Contract, Release


class RoutingConfig(Contract):
    mode: Literal["stable", "canary", "shadow"] = "stable"
    stable_release_id: UUID
    candidate_release_id: UUID | None = None
    canary_weight: int = Field(default=0, ge=0, le=100)
    shadow_sample_rate: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode != "stable" and (
            self.candidate_release_id is None or self.candidate_release_id == self.stable_release_id
        ):
            raise ValueError("Canary and shadow require a distinct candidate.")
        if self.mode != "canary" and self.canary_weight:
            raise ValueError("Canary weight requires canary mode.")
        if self.mode != "shadow" and self.shadow_sample_rate:
            raise ValueError("Shadow percentage requires shadow mode.")
        return self


class Snapshot(Contract):
    id: UUID
    version: int = Field(ge=1)
    config: RoutingConfig
    stable: Release
    candidate: Release | None = None

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if self.stable.id != self.config.stable_release_id:
            raise ValueError("Stable reference does not match.")
        if self.config.candidate_release_id != (self.candidate.id if self.candidate else None):
            raise ValueError("Candidate reference does not match.")
        return self


class Decision(Contract):
    serving_role: Literal["stable", "candidate"]
    release: Release
    canary_bucket: int
    shadow_bucket: int
    shadow_selection: Literal["not_applicable", "not_selected", "selected_execution_deferred"]


def bucket(purpose: str, version: int, key: str) -> int:
    encoded = json.dumps(
        ["sha256-v1", purpose, version, key], ensure_ascii=False, separators=(",", ":")
    ).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest(), "big") % 10000


def decide(snapshot: Snapshot, key: str) -> Decision:
    canary = bucket("canary", snapshot.version, key)
    shadow = bucket("shadow", snapshot.version, key)
    candidate = snapshot.config.mode == "canary" and canary < snapshot.config.canary_weight * 100
    selected = (
        snapshot.config.mode == "shadow" and shadow < snapshot.config.shadow_sample_rate * 100
    )
    release = snapshot.candidate if candidate else snapshot.stable
    assert release is not None
    return Decision(
        serving_role="candidate" if candidate else "stable",
        release=release,
        canary_bucket=canary,
        shadow_bucket=shadow,
        shadow_selection=("selected_execution_deferred" if selected else "not_selected")
        if snapshot.config.mode == "shadow"
        else "not_applicable",
    )


def private_digest(secret: str, purpose: str, value: str) -> str:
    data = json.dumps(["hmac-sha256-v1", purpose, value], separators=(",", ":")).encode()
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


class ShadowPayload(Contract):
    """Request serialization prevents subsequent mutation of the caller's objects."""

    request_id: str
    snapshot: Snapshot
    request_json: str
    selected_at: datetime
    traceparent: str | None = None
    evaluation_run_id: UUID | None = None
    evaluation_case_id: str | None = None

    @classmethod
    def build(
        cls,
        request_id: str,
        snapshot: Snapshot,
        request: ChatRequest,
        selected_at: datetime,
        max_bytes: int,
    ) -> "ShadowPayload":
        job = cls(
            request_id=request_id,
            snapshot=snapshot,
            request_json=request.model_dump_json(),
            selected_at=selected_at,
        )
        if len(job.model_dump_json().encode()) > max_bytes:
            raise ValueError("Shadow payload exceeds the byte limit.")
        return job
