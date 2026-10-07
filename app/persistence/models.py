"""Safe metadata, immutable configuration and correlated serving outcomes."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ModelRelease(Base):
    __tablename__ = "model_releases"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(128))
    supports_temperature: Mapped[bool]
    default_temperature: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("provider IN ('fake','openai','groq')"),
        CheckConstraint(
            "default_temperature IS NULL OR "
            "(supports_temperature AND default_temperature BETWEEN 0 AND 2)"
        ),
    )


class RoutingVersion(Base):
    __tablename__ = "routing_configs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version: Mapped[int] = mapped_column(Identity(), unique=True)
    mode: Mapped[str] = mapped_column(String(16))
    stable_release_id: Mapped[UUID] = mapped_column(ForeignKey("model_releases.id"))
    candidate_release_id: Mapped[UUID | None] = mapped_column(ForeignKey("model_releases.id"))
    canary_weight: Mapped[int]
    shadow_sample_rate: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("mode IN ('stable','canary','shadow')"),
        CheckConstraint("canary_weight BETWEEN 0 AND 100 AND shadow_sample_rate BETWEEN 0 AND 100"),
        CheckConstraint("mode = 'canary' OR canary_weight = 0"),
        CheckConstraint("mode = 'shadow' OR shadow_sample_rate = 0"),
        CheckConstraint(
            "mode = 'stable' OR (candidate_release_id IS NOT NULL "
            "AND candidate_release_id <> stable_release_id)"
        ),
    )


class ActiveConfig(Base):
    __tablename__ = "active_config"
    singleton: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[UUID | None] = mapped_column(ForeignKey("routing_configs.id"))
    __table_args__ = (CheckConstraint("singleton = 1"),)


class ActivationEvent(Base):
    __tablename__ = "activation_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    previous_config_id: Mapped[UUID | None] = mapped_column(ForeignKey("routing_configs.id"))
    config_id: Mapped[UUID] = mapped_column(ForeignKey("routing_configs.id"))
    actor: Mapped[str] = mapped_column(String(32), default="local-cli")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RequestRecord(Base):
    __tablename__ = "requests"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    config_id: Mapped[UUID] = mapped_column(ForeignKey("routing_configs.id"), index=True)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("model_releases.id"))
    serving_role: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    routing_key_digest: Mapped[str] = mapped_column(String(64))
    digest_version: Mapped[str] = mapped_column(String(32), default="hmac-sha256-v1")
    canary_bucket: Mapped[int]
    shadow_bucket: Mapped[int]
    shadow_selection: Mapped[str] = mapped_column(String(40))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (
        CheckConstraint("serving_role IN ('stable','candidate')"),
        CheckConstraint("canary_bucket BETWEEN 0 AND 9999 AND shadow_bucket BETWEEN 0 AND 9999"),
        CheckConstraint(
            "shadow_selection IN ('not_applicable','not_selected','selected_execution_deferred')"
        ),
    )


class Invocation(Base):
    __tablename__ = "invocations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("requests.id"))
    release_id: Mapped[UUID] = mapped_column(ForeignKey("model_releases.id"), index=True)
    serving_role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), index=True)
    max_output_tokens: Mapped[int]
    temperature: Mapped[float | None]
    latency_ms: Mapped[float]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    total_tokens: Mapped[int | None]
    finish_reason: Mapped[str | None] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("request_id", "release_id", "serving_role"),
        CheckConstraint("serving_role IN ('stable','candidate')"),
        CheckConstraint("status IN ('success','failed','cancelled')"),
        CheckConstraint("max_output_tokens > 0 AND latency_ms >= 0"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0"),
        CheckConstraint("total_tokens IS NULL OR total_tokens >= 0"),
    )
