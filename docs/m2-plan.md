# M2: Stable gateway with M1 carryover

M1 was pushed as a skeleton. Its normalization, deadline/cancellation, queue-admission, and trace-export experiments had no implementation or recorded evidence. This milestone carries them forward explicitly. Detailed experiment findings are in [the spike record](spikes/m1-carryover.md).

## Subphases and evidence

| Subphase | Deliverable | Status and evidence |
|---|---|---|
| M2.0a | Provider normalization experiment | Offline verified by synthetic Responses fixtures, nullable/partial usage, malformed output, refusal, and truncation tests. |
| M2.0b | Async timeout and cancellation experiment | Offline verified by actual loopback TCP requests; deadline/cancellation assertions require return in under one second; resources close. |
| M2.0c | Nonblocking queue admission experiment | Offline verified with a real `asyncio.Queue(maxsize=1)` and independent fake serving request. |
| M2.0d | Retrieved exported trace | Verified through the actual Collector and Jaeger; safe trace ID recorded in [trace evidence](spikes/trace-evidence.json). |
| M2.1 | Shared request, response, release, usage and error contracts | Implemented and exercised by contract/validation tests; ADR 002 records decisions. |
| M2.2 | Configurable deterministic fake adapter | Implemented; repeatability, synthetic usage, latency, failure, malformed outcome and cancellation tests. |
| M2.3 | Authenticated stable endpoint | Implemented; fake API tests, request IDs, byte/token/concurrency bounds, safe logs and lifecycle cleanup. |
| M2.4 | Async real-provider adapters | OpenAI and Groq implemented with safe normalization, errors, and one attempt. Groq is verified live; OpenAI is optional. |
| M2.5 | Two model configurations | Verified against real `openai/gpt-oss-20b` and `openai/gpt-oss-120b` through the same authenticated client contract. |
| M2.6 | Final verification and handoff | Local checks and live model evidence supplied; remote CI and author review remain. |

The live-model gate is complete using Groq, following the author's free development choice. The original project permits two configurations on one vendor. Remote CI and author review still need to pass before marking all of M2 complete.

## Decisions and defaults

- Select `fake`, `openai-a`, `openai-b`, `groq-a`, or `groq-b` through `MODELGATE_STABLE_RELEASE`; the client cannot select a provider or model.
- Use Responses APIs via HTTPX, one lifespan-managed client and zero serving retries. OpenAI sends `store=false`; Groq omits its unsupported `store` parameter.
- Require a gateway bearer key at startup. Real serving requires the selected provider's separate key and both distinct model IDs. Do not send secrets in logs or evidence reports.
- Request defaults: 200 output tokens, null temperature. Limits default to 65,536 actual request bytes, 1,024 output tokens, 20 serving slots, and a 10-second total provider deadline.
- Capability flags default to false for real-model temperature support. Requests with unsupported temperature fail with 422 before an upstream call.
- Readiness verifies initialized local serving resources. It performs no paid provider probe and no database check in M2.
- Responses expose `serving_role=stable` and nullable `config_version`. Durable release/configuration history starts in M3.
- Queue admission and exported span exercises are isolated spike evidence. Production shadow consumers and full tracing remain assigned to M4 and M6.

## Local verification

```bash
uv sync --locked --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy app worker scripts
uv run pytest -q
uv run python -m scripts.smoke_gateway
```

Tests use synthetic credentials, isolated environment configuration, mock HTTP responses, and real loopback servers. Ordinary pytest never calls real providers. The smoke command starts an ephemeral Uvicorn server, sends a real HTTP fake-provider request, prints the normalized response, and shuts down.

## Remaining completion gates

- [x] Start Docker, build the gateway image from locked dependencies and verify healthy Compose startup. An actual container-served synthetic chat response is saved in [gateway evidence](spikes/gateway-evidence.json).
- [x] Run `uv run python -m scripts.trace_spike --output docs/spikes/trace-evidence.json`. The span was retrieved through Jaeger's API with `status=verified`.
- [x] Verify two real Groq models with `uv run python -m scripts.verify_models --provider groq --output docs/spikes/model-evidence.json`. Both returned `status=verified`; [saved evidence](spikes/model-evidence.json) contains identifiers and usage without content or keys.
- [ ] Commit/push the implementation and confirm the existing GitHub CI workflow succeeds.
- [ ] Review each subphase's implementation and explain its failure behavior before closing M2.

The 18–24 focused-hour estimate remains a planning budget rather than a claim of elapsed work. Re-estimate the external verification work once Docker, credentials, and model access are available; rebase dates using actual weekly capacity.

## Live model gate — October 7, 2026

Added Groq support for the author's free development route. Its adapter omits unsupported `store`/background parameters and uses low reasoning effort for GPT-OSS. Shared normalization now discards reasoning-text items before assistant-content parsing. The existing OpenAI contract remains covered by regression tests.

| Release | Real model | Result | Input / output / total tokens |
|---|---|---|---|
| `groq-a` | `openai/gpt-oss-20b` | Verified; `stop`, stable role | 77 / 17 / 94 |
| `groq-b` | `openai/gpt-oss-120b` | Verified; `stop`, stable role | 77 / 19 / 96 |

Each check used the gateway's authentication, validation, serving and response normalization. One request was made per model. All 89 offline tests passed, as did lint and type checks. This closes the live-model gate; remote CI and author review remain pending.

## Local handoff evidence — October 5, 2026

Locked installation, lint, formatting, type checks, all 73 offline tests, and all pre-commit checks passed locally. The pre-commit run included tracked and new files. A temporary Uvicorn server and the Compose gateway each served an authenticated synthetic HTTP request. The gateway/PostgreSQL health checks passed. Secret scans reported no findings, and the dependency audit reported no known vulnerabilities.

Compose's first startup found host port 5432 occupied. PostgreSQL now publishes a configurable host port (default 55432), while containers continue using port 5432. No migration or database application record was created by M2.

Trace export was observed through the actual Collector and Jaeger. The live command was run without credentials and correctly exited with a pending configuration message before making any paid request. The remaining inputs are a gateway key, `OPENAI_API_KEY`, and distinct accessible `OPENAI_MODEL_A`/`OPENAI_MODEL_B` values in the ignored local environment.
