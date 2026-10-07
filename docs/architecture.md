# Architecture

The M2 implementation serves stable requests through an authenticated FastAPI endpoint, an async provider interface, and fake, OpenAI or Groq adapters. The planned full system and its invariants are specified in [the project plan](project-plan.md), sections 6–9.

## Planned flow

```mermaid
flowchart LR
  Client --> Gateway[FastAPI gateway]
  Gateway --> Router[Routing engine]
  Router --> Provider[Provider adapter]
  Router --> Queue[Bounded in-process queue]
  Queue --> Consumer[Shadow consumers]
  Consumer --> Provider
  Gateway --> Postgres[(PostgreSQL)]
  Consumer --> Postgres
  Gateway --> Telemetry[Prometheus and OTel]
  Consumer --> Telemetry
```

The serving request waits only for its selected provider. Shadow work is sampled separately, admitted without waiting for queue capacity, and processed by consumers in the gateway process. A shadow failure must never alter a successful serving response. Restart can lose unfinished in-memory jobs; the evaluation report must show such gaps.

## Module boundaries

| Path | Responsibility |
|---|---|
| `app/api` | Public and administrative HTTP routes |
| `app/core` | Settings, authentication, errors, logging |
| `app/domain` | Routing and evaluation decisions with no I/O |
| `app/providers` | Fake and real provider adapters |
| `app/persistence` | Database models and repositories |
| `app/telemetry` | Metrics and tracing helpers |
| `worker` | Queue admission, consumers, evaluation orchestration |

The current process exposes `/v1/chat/completions`, `/health/live`, `/health/ready` and `/metrics/`. It validates configuration at startup, owns one HTTP client through lifespan, bounds serving slots, and invokes one provider within a total deadline. The request boundary counts actual bytes, generates request IDs and emits allowlisted JSON logs. OpenAI normalization stays inside its adapter; the fake provider needs no network.

Database-backed records/configuration, rollout routing, production shadow consumers and evaluation remain planned work. M2's isolated queue and trace experiments provide feasibility evidence only. See [ADR 002](adr/002-stable-api-and-providers.md) and [the M2 status checklist](m2-plan.md).
