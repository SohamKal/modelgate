# Local operations

## Start

```bash
cp .env.example .env
docker compose up --build -d
docker compose --profile observability up --build -d
```

Core gateway: `http://127.0.0.1:8000/health/live` and `/health/ready`. Prometheus: `http://127.0.0.1:9090`. Jaeger: `http://127.0.0.1:16686`. Grafana: `http://127.0.0.1:3000` with credentials from `.env`.

PostgreSQL is reachable on host port `MODELGATE_POSTGRES_PORT` (default 55432); containers use `postgres:5432`. The default host port was changed after the local verification found 5432 already occupied.

The example environment uses a public local demonstration gateway key and fake serving. Missing/short gateway keys fail startup. Real serving requires two distinct model IDs and a separate API key for the selected provider. Select `groq-a`, `groq-b`, `openai-a` or `openai-b` through `MODELGATE_STABLE_RELEASE` and recreate/restart the gateway after changing settings. Model capability flags control optional temperature support. Readiness checks initialization, not remote model access.

## Inspect and stop

```bash
docker compose --profile observability ps
docker compose --profile observability logs gateway postgres
docker compose --profile observability down
```

The named PostgreSQL volume persists across `down`. There are no migration revisions or seed data yet. `alembic.ini` and `migrations/env.py` are ready for M3. Replay, release reports, retention purge, and restart-loss reconciliation remain planned work. The example passwords and gateway key are intended for localhost demonstration.

## M2 verification

The free-development live gate is now verified against both Groq GPT-OSS models. Configure `GROQ_API_KEY`, `GROQ_MODEL_A` and `GROQ_MODEL_B`, then use `uv run python -m scripts.verify_models --provider groq`. Select `--provider openai` explicitly for the optional OpenAI gate. `MODELGATE_VERIFICATION_PROVIDER` controls the default verification provider independently of ordinary serving, which remains fake. To serve Groq requests, choose `groq-a` or `groq-b` as the stable release and recreate the gateway with the new environment.

`uv run python -m scripts.smoke_gateway` starts a temporary fake gateway, makes one actual HTTP request and stops it. `uv run python -m scripts.verify_models` sends one short synthetic request through each configured gateway instance to the selected provider and reports safe verification metadata. These commands do not send request content or credentials to logs; live validation makes provider calls and is excluded from CI.

To verify trace export, start only the trace services and run:

```bash
docker compose --profile observability up -d jaeger otel-collector
uv run python -m scripts.trace_spike
```

The spike publishes one synthetic span through the localhost Collector port and requires matching Jaeger retrieval. If Docker is unavailable, the export gate remains pending. Neither a successful flush nor a mocked retrieval alone closes it. Check [the M2 checklist](m2-plan.md) for the outstanding gates.
