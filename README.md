# Modelgate

Modelgate is a planned provider-neutral LLM gateway for stable, canary, and shadow model releases. The full scope and milestones are in [the project plan](docs/project-plan.md).

The gateway now supports **M3 persistence and routing**: PostgreSQL configuration history, stable/canary serving and shadow sampling decisions. See [the M3 checklist](docs/m3-plan.md), [routing evidence](docs/routing/m3-evidence.json) and [architecture decisions](docs/adr/004-persistence-and-routing.md). M2's two Groq model checks and technical spikes remain recorded in [live evidence](docs/spikes/model-evidence.json) and [spike findings](docs/spikes/m1-carryover.md).

## Architecture at a glance

The planned gateway has one synchronous serving path and a bounded, in-process shadow queue. PostgreSQL will hold immutable release configuration and evaluation metadata. Prometheus, OpenTelemetry Collector, Jaeger, and Grafana support local observability. See [architecture](docs/architecture.md).

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose for the local stack

## Local setup

```bash
cp .env.example .env
uv sync --locked --group dev
docker compose up -d postgres
uv run python -m scripts.migrate
uv run python -m scripts.seed_data
uv run uvicorn app.main:app --reload --no-access-log
```

Copy the environment only for a new checkout; preserve an existing `.env`. The seed selects `fake-stable` without replacing an existing active version. The example environment includes public localhost demonstration gateway/hash keys. Open `http://127.0.0.1:8000/docs` and use **Authorize** with the gateway key, or send:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Authorization: Bearer local-client-demo-only' \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Classify: I was charged twice."}],"max_output_tokens":200}'
```

The response contains deterministic fake content, a generated request ID, `release_name=fake-stable`, `serving_role=stable`, synthetic usage, a durable `config_version` and `recording_status=recorded`. Readiness at `/health/ready` checks PostgreSQL, the active config and credentials without calling a real model. Liveness is `/health/live`; process metrics are `/metrics/`. To exercise an isolated adapter HTTP request without PostgreSQL:

```bash
uv run python -m scripts.smoke_gateway
```

## Free Groq verification

Create a free-plan key at [Groq Console](https://console.groq.com/keys) and save it as `GROQ_API_KEY` in your ignored `.env`. The example targets are `openai/gpt-oss-20b` and `openai/gpt-oss-120b`; account-specific [quotas](https://console.groq.com/docs/rate-limits) apply.

```bash
uv run python -m scripts.verify_models --provider groq --check-config
uv run python -m scripts.verify_models --provider groq --output docs/spikes/model-evidence.json
```

The check sends no requests. Verification sends one synthetic request per model through the gateway, capped at up to 512 output tokens for reasoning, and records metadata/usage without keys, output content or reasoning text. Each result must have completed nonempty text, the expected Groq model ID, release and serving role.

`MODELGATE_VERIFICATION_PROVIDER=groq` selects the command's default; `--provider` overrides it. This command tests adapters in an explicitly isolated configuration. Ordinary M3 serving uses registered database releases; see the configuration commands below. `MODELGATE_STABLE_RELEASE` no longer overrides PostgreSQL. See [ADR 003](docs/adr/003-groq-live-verification.md) for provider differences.

## Optional OpenAI configurations

For isolated verification, supply `OPENAI_API_KEY`, `OPENAI_MODEL_A`, and `OPENAI_MODEL_B` with two distinct accessible model IDs in your ignored `.env`. For ordinary serving, register and activate a database release with the configured OpenAI key. The client's endpoint and request shape stay the same. Temperature is omitted when null and there is no release default; enable temperature support only when that model supports it. OpenAI requests use `store=false` and make one attempt.

Run the explicit live gate once you have configured both models:

```bash
uv run python -m scripts.verify_models --provider openai
```

Check settings first without making a paid request:

```bash
uv run python -m scripts.verify_models --provider openai --check-config
```

Configuration errors name only missing or invalid settings and never print their values. The selected provider requires its own key; the offline smoke command works without one. Gemini is not integrated.

This sends one short synthetic request through each configured gateway instance to the real provider. It is excluded from CI. Provider credentials are separate from the gateway bearer key.

## Docker Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose --profile observability up --build -d
```

The core profile starts PostgreSQL and the gateway. Container startup applies migrations and the repeatable fake seed before starting Uvicorn. A seed never resets an existing active configuration. The observability profile adds Prometheus (`localhost:9090`), Jaeger (`localhost:16686`), and Grafana (`localhost:3000`). Grafana's local credentials are set in `.env`. Full instrumentation and dashboard panels arrive in M6. Verify the carryover trace spike independently with:

```bash
docker compose --profile observability up -d jaeger otel-collector
uv run python -m scripts.trace_spike
```

The command must retrieve its trace from Jaeger before reporting `verified`. The container image build and actual trace export/retrieval were verified on October 5, 2026.

## Development checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app worker scripts
uv run pytest
uv run pre-commit run --all-files
```

Required database verification uses an isolated PostgreSQL database ending in `_test`:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://modelgate:test-only@127.0.0.1:55433/modelgate_test uv run pytest --require-postgres # pragma: allowlist secret (public disposable test credentials)
DATABASE_URL=postgresql+asyncpg://modelgate:test-only@127.0.0.1:55433/modelgate_test uv run python -m scripts.verify_routing --output docs/routing/m3-evidence.json # pragma: allowlist secret (public disposable test credentials)
```

These commands require a test container described in [operations](docs/operations.md). The routing rehearsal changes that test database's active configuration and uses fake providers only. Its 10,000-key allocation checks are pure routing calculations; the bounded HTTP batch demonstrates gateway/database integration.

## Configure routing locally

```bash
uv run python -m scripts.configure_routing releases
uv run python -m scripts.configure_routing history
uv run python -m scripts.configure_routing activate --mode canary --stable fake-stable --candidate fake-candidate --canary-weight 10 --expected-version 1
```

Use the actual current version from `history`; a stale expected version is rejected. New requests use the committed version immediately; in-flight calls keep their previous snapshot. Candidate errors are returned as serving errors without fallback.

For shadow sampling, use `--mode shadow --shadow-sample-rate 10` with the same release references and current expected version. M3 records sampling decisions and serves stable; candidate shadow execution starts in M4.

To register a real release, save a JSON definition such as `{"name":"groq-small-v1","provider":"groq","model":"openai/gpt-oss-20b","supports_temperature":false}` and run `uv run python -m scripts.configure_routing register path/to/release.json`. Then activate it as `--stable groq-small-v1 --mode stable`. Its provider key must already be configured; registration contains no credentials. Changing model/capability/default parameters requires a new release name.

## Roadmap and limits

After the remaining M2 gates pass, M3 adds persistence and routing configuration. Shadow consumers, evaluation, and release controls follow the sequence in the plan. This is a single-host portfolio project. The planned in-memory shadow queue will lose unfinished jobs on restart.

See [API notes](docs/api.md), [operations](docs/operations.md), and [security](docs/security.md).
