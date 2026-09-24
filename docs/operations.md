# Local operations

## Start

```bash
cp .env.example .env
docker compose up --build -d
docker compose --profile observability up --build -d
```

Core gateway: `http://127.0.0.1:8000/health/live`. Prometheus: `http://127.0.0.1:9090`. Jaeger: `http://127.0.0.1:16686`. Grafana: `http://127.0.0.1:3000` with credentials from `.env`.

## Inspect and stop

```bash
docker compose --profile observability ps
docker compose --profile observability logs gateway postgres
docker compose --profile observability down
```

The named PostgreSQL volume persists across `down`. This scaffold has no migration revisions or seed data yet. `alembic.ini` and `migrations/env.py` are ready for the first persistence slice. Readiness checks, replay, release reports, retention purge, and restart-loss reconciliation remain planned work. Do not use the example passwords for a shared or remotely reachable service.
