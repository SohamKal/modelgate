# Modelgate

Modelgate is a planned provider-neutral LLM gateway for stable, canary, and shadow model releases. The full scope and milestones are in [the project plan](docs/project-plan.md).

The **M2 stable gateway implementation** is available: an authenticated chat endpoint, deterministic offline provider, and OpenAI/Groq Responses adapters. All four M1 technical spikes have verification evidence. The live-model gate passed with two Groq models on October 7, 2026; remote CI and review remain. See [the M2 checklist](docs/m2-plan.md), [live evidence](docs/spikes/model-evidence.json), and [spike findings](docs/spikes/m1-carryover.md).

## Architecture at a glance

The planned gateway has one synchronous serving path and a bounded, in-process shadow queue. PostgreSQL will hold immutable release configuration and evaluation metadata. Prometheus, OpenTelemetry Collector, Jaeger, and Grafana support local observability. See [architecture](docs/architecture.md).

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose for the local stack

## Local setup

```bash
cp .env.example .env
uv sync --locked --group dev
uv run uvicorn app.main:app --reload --no-access-log
```

The example environment selects the fake provider and includes a public localhost demonstration key. Open `http://127.0.0.1:8000/docs` and use **Authorize** with that key, or send:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Authorization: Bearer local-client-demo-only' \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Classify: I was charged twice."}],"max_output_tokens":200}'
```

The response contains deterministic fake content, a generated request ID, `release_name=fake`, `serving_role=stable`, synthetic usage, and `config_version=null`. Liveness is `/health/live`; readiness is `/health/ready`; process metrics are `/metrics/`. To exercise an actual local HTTP request without configuring a running server:

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

`MODELGATE_VERIFICATION_PROVIDER=groq` selects the command's default; `--provider` overrides it. Default application serving remains `fake`. To serve ordinary Groq traffic, select `MODELGATE_STABLE_RELEASE=groq-a` or `groq-b` and restart/recreate the gateway. See [ADR 003](docs/adr/003-groq-live-verification.md) for provider differences.

## Optional OpenAI configurations

In your ignored `.env`, supply `OPENAI_API_KEY`, `OPENAI_MODEL_A`, and `OPENAI_MODEL_B` with two distinct accessible model IDs. Select `MODELGATE_STABLE_RELEASE=openai-a` or `openai-b`, then restart the gateway. The client's endpoint and request shape stay the same. Temperature is omitted when null; enable the matching capability setting only when that model supports it. OpenAI requests use `store=false` and make one attempt.

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

The core profile starts the gateway and PostgreSQL. PostgreSQL is reserved for M3; M2 does not read or write its records. The observability profile adds Prometheus (`localhost:9090`), Jaeger (`localhost:16686`), and Grafana (`localhost:3000`). Grafana's local credentials are set in `.env`. Full instrumentation and dashboard panels arrive in M6. Verify the carryover trace spike independently with:

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

## Roadmap and limits

After the remaining M2 gates pass, M3 adds persistence and routing configuration. Shadow consumers, evaluation, and release controls follow the sequence in the plan. This is a single-host portfolio project. The planned in-memory shadow queue will lose unfinished jobs on restart.

See [API notes](docs/api.md), [operations](docs/operations.md), and [security](docs/security.md).
