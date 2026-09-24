# Modelgate

Modelgate is a planned provider-neutral LLM gateway for stable, canary, and shadow model releases. The full scope and milestones are in [the project plan](docs/project-plan.md).

This repository is at the **foundation scaffold** stage. It has a runnable FastAPI process, a PostgreSQL and observability Compose layout, development tooling, and documentation structure. Chat routing, provider adapters, shadow evaluation, database tables, and release administration are not implemented yet.

## Architecture at a glance

The planned gateway has one synchronous serving path and a bounded, in-process shadow queue. PostgreSQL will hold immutable release configuration and evaluation metadata. Prometheus, OpenTelemetry Collector, Jaeger, and Grafana support local observability. See [architecture](docs/architecture.md).

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose for the local stack

## Local setup

```bash
cp .env.example .env
uv sync --locked --group dev
uv run uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/health/live`, `http://127.0.0.1:8000/metrics`, or `http://127.0.0.1:8000/docs`. The API docs currently contain only the liveness endpoint.

## Docker Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose --profile observability up --build -d
```

The core profile starts the gateway and PostgreSQL. The observability profile adds Prometheus (`localhost:9090`), Jaeger (`localhost:16686`), and Grafana (`localhost:3000`). Grafana's local credentials are set in `.env`. The collector and dashboards are scaffolded; useful traces and panels arrive with the corresponding implementation milestones.

## Development checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app worker
uv run pytest
uv run pre-commit run --all-files
```

## Roadmap and limits

The next vertical slice is a deterministic fake provider and `POST /v1/chat/completions`. Canary routing, shadow consumers, persistence, evaluation, and release controls follow the sequence in the plan. This is a single-host portfolio project, not a production service. The in-memory shadow queue will lose unfinished jobs on restart.

See [API notes](docs/api.md), [operations](docs/operations.md), and [security](docs/security.md).
