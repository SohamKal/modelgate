# Local operations

## Start

```bash
cp .env.example .env
docker compose up --build -d
docker compose --profile observability up --build -d
```

Core gateway: `http://127.0.0.1:8000/health/live` and `/health/ready`. Prometheus: `http://127.0.0.1:9090`. Jaeger: `http://127.0.0.1:16686`. Grafana: `http://127.0.0.1:3000` with credentials from `.env`.

PostgreSQL is reachable on host port `MODELGATE_POSTGRES_PORT` (default 55432); containers use `postgres:5432`. The default host port was changed after the local verification found 5432 already occupied.

Copy `.env.example` only for a new checkout; preserve any configured `.env`. Container startup runs migrations and the repeatable fake seed before serving. Missing/short gateway or content-hash keys fail startup. The hash key must differ from all API credentials. PostgreSQL's active configuration controls ordinary serving; `MODELGATE_STABLE_RELEASE` is only used by isolated verification tools. Registered releases specify temperature capability/defaults. Readiness checks PostgreSQL, the active configuration and available credentials without a provider call.

For a host Python process, start PostgreSQL and run:

```bash
uv run python -m scripts.migrate
uv run python -m scripts.seed_data
uv run uvicorn app.main:app --reload --no-access-log
```

The host `DATABASE_URL` uses localhost port 55432; Compose overrides it with the container address. Database credentials and the content-hash key stay in the ignored environment. The seed registers `fake-stable` and `fake-candidate`, activates stable only when no active config exists, and preserves all later changes.

## Configure and inspect M3

```bash
uv run python -m scripts.configure_routing releases
uv run python -m scripts.configure_routing history
uv run python -m scripts.configure_routing activate --mode canary --stable fake-stable --candidate fake-candidate --canary-weight 10 --expected-version 1
```

Replace `1` with the actual active version from history. Failed/stale changes preserve the active pointer; successful changes create a new immutable version/audit record. A release name cannot be reused with changed parameters. `register path/to/release.json` accepts the validated release shape documented in README. Credentials remain separate environment settings. Local CLI access is trusted; HTTP admin authentication/promotion/rollback arrive in M7.

Use `--mode stable --stable fake-stable --expected-version CURRENT` to serve stable again. Shadow sampling uses `--mode shadow --stable fake-stable --candidate fake-candidate --shadow-sample-rate 10 --expected-version CURRENT`. M3 records selected copies as execution deferred; it does not enqueue or call them.

A configuration read outage returns `configuration_unavailable`/503 without calling a provider. Metadata writes are bounded; a successful provider response survives failed recording with `recording_status=degraded`. Safe `recording_degraded` events identify detected loss. No provider retry repairs metadata. There is no stale-config cache. Raw content/key/task labels are not stored. Retention/purge and restart-loss accounting remain later work.

## Disposable PostgreSQL verification

Use an isolated test container; these commands must not point at the ordinary development database:

```bash
docker run -d --name modelgate-m3-test --label modelgate.disposable-test=true -e POSTGRES_USER=modelgate -e POSTGRES_PASSWORD=test-only -e POSTGRES_DB=modelgate_test -p 127.0.0.1:55433:5432 postgres:16.6-alpine
TEST_DATABASE_URL=postgresql+asyncpg://modelgate:test-only@127.0.0.1:55433/modelgate_test uv run pytest --require-postgres # pragma: allowlist secret (public disposable test credentials)
DATABASE_URL=postgresql+asyncpg://modelgate:test-only@127.0.0.1:55433/modelgate_test uv run python -m scripts.verify_routing --output docs/routing/m3-evidence.json # pragma: allowlist secret (public disposable test credentials)
```

Tests migrate and clear synthetic test tables; the rehearsal changes test configuration/history and sends bounded actual HTTP fake requests. Both require a database name ending in `_test`. Without `TEST_DATABASE_URL`, ordinary pytest skips the PostgreSQL suite; the completion command and CI require it. Wait for PostgreSQL to accept connections before running. To inspect metadata, join `requests` to `routing_configs`, `model_releases` and `invocations`; inspect `activation_events` for configuration changes. No content preview is available in M3.

Migration upgrade/downgrade/re-upgrade verification is limited to this disposable database. Production data migration rollback is not a supported demo operation. Stop the test container after verification with `docker stop modelgate-m3-test`.

## Inspect and stop

```bash
docker compose --profile observability ps
docker compose --profile observability logs gateway postgres
docker compose --profile observability down
```

The named PostgreSQL volume persists across `down`; committed configuration and metadata survive gateway restarts. The initial revision is `a701c3d717e0`. Replay, release reports, retention purge, and restart-loss reconciliation remain planned work. The example passwords and API/hash keys are intended for localhost demonstration.

## M2 verification

The free-development live gate is verified against both Groq GPT-OSS models. Configure `GROQ_API_KEY`, `GROQ_MODEL_A` and `GROQ_MODEL_B`, then use `uv run python -m scripts.verify_models --provider groq`. Select `--provider openai` explicitly for the optional OpenAI gate. `MODELGATE_VERIFICATION_PROVIDER` controls isolated verification independently of ordinary database-selected serving. For normal Groq traffic, register and activate a Groq release through the M3 CLI.

`uv run python -m scripts.smoke_gateway` starts a temporary fake gateway, makes one actual HTTP request and stops it. `uv run python -m scripts.verify_models` sends one short synthetic request through each configured gateway instance to the selected provider and reports safe verification metadata. These commands do not send request content or credentials to logs; live validation makes provider calls and is excluded from CI.

To verify trace export, start only the trace services and run:

```bash
docker compose --profile observability up -d jaeger otel-collector
uv run python -m scripts.trace_spike
```

The spike publishes one synthetic span through the localhost Collector port and requires matching Jaeger retrieval. If Docker is unavailable, the export gate remains pending. Neither a successful flush nor a mocked retrieval alone closes it. Check [the M2 checklist](m2-plan.md) for the outstanding gates.
