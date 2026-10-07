# M3: Persistence and routing

**Planning date:** October 7, 2026  
**Status:** Implemented and locally verified; publication/remote CI deferred by the author, sign-off pending

**Predecessor:** M2 stable gateway and provider contracts  
**Project-plan mapping:** WBS 3.1–3.5; milestone “M3 Routing complete”

## Outcome

The existing authenticated `POST /v1/chat/completions` will use a PostgreSQL-backed configuration snapshot to select a stable or candidate release. It will return the selected release, serving role and durable configuration version, and record safe routing/invocation metadata. Canary allocation will be repeatable for a key within one configuration version. Shadow mode will serve stable and record whether a candidate copy was selected for later execution.

Work through the subphases in order. Before starting implementation of each subphase, expand it into its own task plan using the template below. Tests, a small demonstration and review evidence close each gate.

## Starting point

- M2 has a working fake provider, OpenAI/Groq adapters, authentication, limits, safe errors/logs, deadlines and lifecycle cleanup. Two Groq models have live verification evidence.
- PostgreSQL, SQLAlchemy, asyncpg and Alembic are configured dependencies. `app/persistence/models.py` contains only the declarative base; no application tables or migration revisions exist.
- Release selection currently comes from startup settings. Release names are a fixed literal list; responses support only the stable role and a nullable configuration version.
- The gateway does not read or write PostgreSQL. Readiness currently checks initialization only. CI has no PostgreSQL service.

## Scope and milestone boundaries

M3 delivers database foundations, immutable release definitions/configurations, a transactionally updated active pointer, pure routing decisions, stable/canary serving, shadow selection and safe recording. A local CLI will seed and activate configuration through the same service layer that future admin routes can reuse.

M4 owns queue admission, consumers, candidate shadow calls, expiry/retries, interrupted-job accounting, retained content and purge. M5 owns evaluation runs/cases, scores and reports. M6 owns full metrics/traces/dashboards. M7 owns separate admin authentication, HTTP administration, promotion and rollback. The minimal configuration activation audit record belongs in M3 so durable changes already preserve history.

Shadow selection in M3 must be reported as a decision only. A selected copy has not been queued, invoked or evaluated.

## Subphase sequence

| Subphase | Work | Required completion evidence | Estimate |
|---|---|---|---:|
| M3.0 — Decisions and contracts | Specify schema, routing rules, snapshot boundaries, recording behavior and configuration authority; write ADR 004. | Reviewed examples for all three modes, invalid settings and failure paths; contract/schema sketches agreed before migration work. | 1–2h |
| M3.1 — Database foundation | Implement engine/session lifecycle, core tables, constraints, initial migration and PostgreSQL test fixtures. | Migration applies to an empty real PostgreSQL database; constraints and transaction rollback pass; connections close. | 3–4h |
| M3.2 — Release and configuration lifecycle | Implement immutable registration, validation, idempotent seed, config history, atomic activation and local CLI. | Repeated seed preserves history; invalid/failed/conflicting activation leaves a valid active pointer; restart resolves the same committed version. | 3–4h |
| M3.3 — Pure routing engine | Produce stable, canary and shadow decisions from a pinned snapshot and routing key. | Determinism, 0/100 boundaries, fixed hash vectors and a 10,000-key distribution report pass. | 2–3h |
| M3.4 — Stable serving with persistence | Resolve DB configuration, invoke the chosen adapter once, record request/invocation metadata and extend response/readiness. | One authenticated fake request returns a non-null config version and joins to its saved release/decision/invocation. DB failure behavior passes. | 3–4h |
| M3.5 — Canary serving | Execute the router-selected stable or candidate release through the same endpoint. | Same request shape works for both roles; exactly one provider call occurs; candidate failures return controlled errors without fallback. | 2–3h |
| M3.6 — Shadow selection and M4 handoff | Persist independent sampling decisions and define a bounded, pinned job payload contract. | Stable always serves; selected/not-selected decisions are recorded; no candidate call occurs; snapshots survive a later activation unchanged. | 2–3h |
| M3.7 — Failure and CI verification | Exercise real PostgreSQL faults, concurrent activation/requests, privacy and regression behavior; add DB-backed CI. | Offline provider tests plus real PostgreSQL tests pass in CI, including recording degradation and activation failure. | 3–4h |
| M3.8 — Review and handoff | Update quickstart/API/operations, save reproducible routing evidence and review every subphase. | Clean-database rehearsal succeeds; commit is pushed, CI passes, author can explain each gate and M4 limitations. | 1–2h |

The detailed budget is **20–29 focused hours**, revising the original 16-hour M3 allocation to include real PostgreSQL CI, failure cases and review. Re-estimate after M3.2. Calendar dates remain unset until weekly availability is known.

## M3.0 — Decisions and contracts

Record the following proposed defaults in ADR 004 and confirm them during this subphase:

1. Use modes `stable`, `canary` and `shadow`. Percentages are integer values from 0 to 100. Stable mode has zero canary/shadow percentages; canary mode has zero shadow percentage; shadow mode has zero canary percentage. Canary/shadow require a distinct candidate release.
2. Separate immutable model releases and routing versions from a mutable singleton active-config pointer. Configuration versions are unique, monotonically allocated, and may have gaps. A version is never edited to change its behavior.
3. Read the active pointer and referenced configuration/releases as one consistent snapshot for each request. Materialize validated immutable domain values before calling a provider. Activation affects only subsequent snapshots.
4. PostgreSQL becomes the serving configuration authority. Environment variables supply database/provider credentials and bootstrap values; changing an existing model definition requires registering a new release. The old stable-release setting becomes a documented bootstrap input rather than a second live authority.
5. Keep provider identifiers allowlisted; allow bounded release names beyond M2's fixed five names. Persist model identifiers, capabilities and allowed parameter defaults, never arbitrary upstream URLs or credentials. Validate supported parameters against the selected release before invocation.
6. Preserve client-supplied generation parameters; specify precedence for release defaults and global limits. The effective parameters used must be reconstructable from the pinned release and safe invocation metadata.
7. Extend `serving_role` to `stable | candidate`. Database-backed successful responses have a non-null `config_version` and additive `recording_status=recorded | degraded`.
8. Keep raw content storage disabled throughout M3. Specify a canonical request serialization and a keyed content hash for correlation; keep its secret outside the database. Persist a routing-key digest rather than the raw caller key. This refines the project plan's raw routing-key column to reduce unnecessary retained input. Document digest versioning and key-rotation consequences.

**Gate:** ADR, examples and contract tests specify how these decisions interact. Resolve the schema and error vocabulary before M3.1; document any change from these proposed defaults.

## M3.1 — Database foundation

Build only the tables needed by this milestone:

| Entity | Purpose and important constraints |
|---|---|
| Model release | UUID, unique bounded name, provider/model, validated capabilities/defaults, UTC creation time; immutable definition. |
| Routing configuration | UUID, unique integer version, mode, stable/candidate foreign keys, percentage checks, creation time; immutable definition. |
| Active configuration | Singleton pointer referencing a persisted version; updated transactionally. |
| Request / routing decision | Ingress request ID, configuration/release references, selected serving role, hash/key digest, task metadata, bucket/sampling decision and UTC time. |
| Invocation | Request/release/role references, effective safe parameters, status, provider latency, nullable usage, finish reason and safe error code. Unique logical serving result per request/release/role. |
| Activation audit event | Previous/new version, UTC time and safe local actor identifier; committed with activation. |

Create request/invocation/configuration lookup indexes and enforce relationships at the database boundary. Use short-lived async sessions per operation/task, bounded pooling and database timeouts, and dispose the engine on shutdown. Do not hold a database transaction while awaiting an LLM response. Disable SQL parameter logging where it could expose submitted values.

Use real PostgreSQL for migration and repository tests. Disposable test databases must have explicit test configuration; tests must not clear the developer's normal database. Review generated migration SQL. Rehearse upgrade and downgrade/re-upgrade only against an empty disposable database.

**Gate:** Migration, constraint violations, rollback and lifecycle cleanup have reproducible evidence. Later shadow/evaluation tables will arrive through later migrations.

## M3.2 — Release and configuration lifecycle

- Add repository/service methods to register releases, create routing versions, inspect history and activate a validated version.
- Seed two distinguishable fake releases, `fake-stable` and `fake-candidate`, and one stable configuration. Optional Groq/OpenAI releases can be registered from local model settings without making provider calls.
- Make seed repeatable: unchanged definitions reuse existing records; changed definitions produce a clear conflict or require a new release name. Seed must not reset an already active configuration.
- Provide local `scripts.seed_data` and `scripts.configure_routing` entry points. The latter accepts an explicit mode, registered release references and percentages; it does not automatically promote a candidate.
- Lock the active pointer during activation and use an expected-current-version check to reject stale concurrent changes. Configuration creation, activation and audit persistence must have clear transaction boundaries; activation and its audit commit together.
- Enforce release/configuration immutability in the supported write paths and database guards selected in ADR 004. A write failure cannot publish an uncommitted active version.
- Validate required provider credentials when resolving a usable release; report safe configuration errors without echoing secrets.

**Gate:** Real PostgreSQL tests cover repeatable seed, history, immutability, invalid mode/weight combinations, unknown or identical candidate, stale activation, transaction failure and restart durability.

## M3.3 — Pure routing engine

The router performs no provider calls or database writes. It returns a decision containing the configuration version, pinned release references, serving role, effective routing-key digest, bucket and shadow selection.

- Use SHA-256 over an explicitly encoded tuple of algorithm version, decision purpose, configuration version and key. Fix serialization with test vectors; do not use Python's process-dependent `hash()`.
- Map the digest to one of 10,000 buckets. Candidate serves when the canary bucket is below `canary_weight * 100`.
- Use a different decision-purpose prefix for shadow sampling so it has a separate hash decision. In shadow mode, stable serves regardless of the sampling result.
- If `request_key` is absent, use the generated ingress request ID. Reusing a supplied key preserves routing only within one config version; it does not deduplicate responses or provider calls. New versions may change assignment.

**Gate:** Cover 0%, 100%, threshold boundaries, identical keys across process restarts, missing-key behavior and invalid configs. Generate a reproducible report over at least 10,000 unique synthetic keys; a configured 10% split must be within ±1.5 percentage points. Exercise shadow sampling separately and prove that changing it cannot select candidate serving.

## M3.4 — Stable serving with persistence

Integrate the DB snapshot and routing service into the existing request path. Resolve adapters from the selected release using a lifespan-managed provider registry/shared HTTP client; preserve offline fake tests and synthetic real-provider fixtures.

1. Authenticate and validate input using the existing boundary.
2. Resolve the configuration/release snapshot within a bounded database deadline.
3. Record the request and stable routing decision in a short transaction.
4. Invoke the stable provider once using existing serving slots and deadline.
5. Persist its outcome in a short transaction and return normalized serving metadata.

Configuration resolution failures return controlled `503` before a provider call. Once a valid snapshot exists, metadata recording failures must not prevent serving; a successful response is returned with `recording_status=degraded`. If the final write fails, preserve successful content, usage and release metadata. If an earlier write failed, attempt a complete bounded final record where feasible, and report `recorded` only when the required correlated records committed. Never repeat the provider call to repair database records.

Record provider failures with safe status/error codes where possible, while preserving their original client status even when recording also fails. Cancellation must propagate and release resources; outcome recording is bounded best effort and does not promise complete crash history. Readiness now checks database access and a usable active configuration with bounded checks. Liveness remains independent of dependencies.

**Gate:** Manual authenticated fake HTTP request joins to request/config/release/invocation records. Tests cover successful usage, missing usage, provider failure, deadline, cancellation, missing config, read outage and writes failing before/after invocation. Recording failures emit safe structured events; full telemetry counters remain in M6.

## M3.5 — Canary serving

Execute the selected stable or candidate release, with the same public request shape. Return `serving_role=candidate` when candidate served. Store the exact configuration and release snapshot used even if activation occurs while the provider is running.

Canary candidate failure is a serving failure and returns the existing controlled provider error. No fallback, second provider attempt or retry is introduced. Preserve the serving concurrency limit across both roles. Unsupported parameters fail before any upstream call for the selected release.

**Gate:** API tests prove stable-only, 0%, 100% and mixed routing, repeated-key selection, correct persisted metadata, one call per request, parameter validation and candidate failures. A bounded fake batch demonstrates the split without credentials.

## M3.6 — Shadow selection and M4 handoff

Serve stable and persist whether shadow sampling selected the candidate. Define a job payload with request ID, exact config version, complete pinned release definitions, defensive copies of normalized request/effective parameters and selection time. Leave evaluation identifiers and trace context optional for their later milestones. Validate the serialized payload size against an explicit bound in addition to the ingress byte limit.

This is a contract for M4: do not start consumers, call the candidate, create a durable delivery promise or mark selected requests completed. Persist distinct selection outcomes such as `not_applicable`, `not_selected` and `selected_execution_deferred` so later reports cannot count selections as executed pairs.

**Gate:** 0/100 and mixed samples behave correctly; all client responses are stable; candidate call count is zero. A payload created before activation retains its original version/releases/parameters afterward, and request mutations cannot alter it.

## M3.7 — Failure and CI verification

Add a disposable PostgreSQL service to CI and apply migrations before DB tests. Keep tests independent of provider keys and paid network calls. Existing unit/adapter tests remain runnable without Docker; the required database suite must run in CI rather than silently skip.

Required combined scenarios:

- Empty database, migration, repeated seed and gateway restart.
- Database unavailable before configuration resolution: `503`, failed readiness, zero provider calls.
- Recording failure after a valid snapshot: original serving outcome preserved, degraded success metadata where applicable, safe event, one provider attempt.
- Failed/stale activation: prior active version preserved and no success audit for a rolled-back transaction.
- Concurrent requests and activation: each request uses one complete snapshot; no mixed version/release metadata.
- Stable and candidate failures, timeout/cancellation and connection/serving-slot cleanup.
- Raw prompts, outputs, authorization headers, provider/database/hash secrets and raw exceptions absent from persisted metadata and logs.
- Distribution evidence and existing M2 authentication/normalization/limit regression tests.

**Gate:** Locked installation, lint, formatting, types, secret scan, dependency audit and required PostgreSQL/offline suites pass on the pushed commit.

## M3.8 — Review and handoff

Update README, API, architecture and operations with migration/seed/configuration commands, response additions, database readiness and safe failure semantics. Add a small offline routing verification script and save metadata-only evidence in `docs/routing/m3-evidence.json`.

Evidence should identify the revision, database migration, tested versions, fake release IDs, sample size, expected/observed percentage, boundary results and shadow selection counts. It must state that shadow execution is deferred. Rehearse from an empty disposable database through stable, 10% canary and sampled shadow decisions, then inspect correlated rows.

**Gate:** Author review explains routing determinism, config immutability, transaction boundaries, one-attempt serving, degraded recording and the M4 handoff. Push and verify CI before marking M3 complete.

## Completion checklist

- [x] M3.0 decisions/contracts and ADR reviewed.
- [x] Initial migration and real PostgreSQL tests pass.
- [x] Releases/configurations preserve immutable history; seed is repeatable.
- [x] Activation/audit are atomic; failed or stale changes preserve active state.
- [x] Stable requests return and persist durable configuration versions.
- [x] Canary routing passes 0/100 boundaries and the 10,000-key tolerance gate.
- [x] Candidate serving is distinguishable and makes one attempt.
- [x] Shadow sampling is independent, pinned and recorded without candidate execution.
- [x] Database outage/recording failures meet the documented response behavior.
- [x] Persistent metadata/logs contain no raw content or credentials.
- [ ] Clean-database walkthrough, evidence, documentation and author review complete.
- [x] Implementation committed locally as `caa5a23` on `codex/m3-persistence-routing`.
- [ ] Branch published and required remote CI succeeds; deferred at the author's request.

## Template for each individual subphase plan

1. Goal and prerequisites.
2. Concrete contracts and decisions to settle.
3. Ordered implementation tasks and affected files.
4. Required tests and manual demonstration.
5. Failure behavior, privacy checks and regression risks.
6. Completion evidence and review questions.
7. Estimate, actual observations and handoff to the next subphase.

Implementation covers M3.0–M3.8. The review questions and failure explanations are recorded in [M3 review notes](m3-review.md); author sign-off and remote CI remain final gates.

The author requested keeping the implementation local on October 7, 2026. No M3 branch or pull request was published, and remote CI has not run. The local gateway/PostgreSQL containers are healthy; the disposable verification container was stopped after testing.

## Implementation evidence — October 7, 2026

- Initial migration `a701c3d717e0` applied against real PostgreSQL 16.6; downgrade to base, re-upgrade and Alembic model comparison passed in a disposable database.
- Local regression suite: 121 tests passed, including PostgreSQL tests with `--require-postgres`; Ruff and mypy passed.
- [Actual HTTP routing rehearsal](routing/m3-evidence.json): 74 synthetic fake requests, all with matching recorded invocations; stable, canary and shadow 0/100 boundaries passed.
- The 10,000-key corpus selected 1,023 canary keys at configured 10% (10.23%) and 955 shadow keys (9.55%), within ±1.5 percentage points. No real provider calls were made. Shadow modes had zero candidate serving calls.
- Configuration history, atomic/stale activation, pinned requests, privacy, recording degradation/repair, read deadlines and cancellation have targeted tests. See [review notes](m3-review.md).
- Docker image startup now migrates and seeds before serving; [local container verification](routing/container-evidence.json) confirms readiness, an authenticated response and the correlated PostgreSQL rows. The existing ignored environment was extended with a host database URL and an independent random content-hash key; existing credentials were preserved.

The original 20–29h estimate remains a planning budget, not elapsed-time evidence. Implementation is ready for the final CI/review gate; allow approximately 1–2 focused hours for author walkthrough and any resulting corrections.

## Implementation references

Consult the versions pinned in `uv.lock` when implementing. Async session ownership and lifecycle guidance comes from [SQLAlchemy's asyncio documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html). Migration workflow guidance comes from [the Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html). These references inform implementation; PostgreSQL tests establish project behavior.
