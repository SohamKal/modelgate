# ADR 004: Durable configuration and deterministic routing

**Date:** October 7, 2026  
**Status:** Implemented; verification recorded in the M3 plan

## Decisions

PostgreSQL holds immutable model releases and routing versions. Database triggers reject updates/deletes of definitions and activation audit events. A singleton pointer selects the active version. Activation locks that pointer, checks the expected current version, inserts the new version/audit and commits the pointer in one transaction. Identity-generated versions may have gaps after rollback.

Modes are `stable`, `canary` and `shadow`. Percentages are integers from 0 to 100. Canary/shadow need distinct candidates; other modes cannot have their percentage enabled. Stable mode may retain an inactive candidate reference for later local configuration changes. Snapshot validation checks release references. Immutable rows allow one active-pointer read followed by loading its pinned definitions without observing mixed changes.

The router hashes JSON `["sha256-v1", purpose, configuration_version, key]` with SHA-256, interprets the full digest as a big-endian integer and takes modulo 10,000. Candidate serves below `canary_weight * 100`; shadow uses purpose `shadow` independently of purpose `canary`. Missing keys use generated ingress IDs. Keys do not deduplicate execution. New versions may reassign a key.

Normal serving requires PostgreSQL and a separate content-hash key. Environment model names and the old stable selector are used by isolated adapter verification/bootstrap only; they never override active database configuration. Provider credentials stay in settings and resolve through an allowlisted adapter registry. CLI release registration accepts validated model IDs/capabilities, not arbitrary URLs or secrets. Explicit request temperature overrides a release default; otherwise that default applies. The global output limit remains authoritative.

Each request materializes immutable config/releases before provider invocation. Sessions and transactions are short and do not span provider calls. Database operations have bounded deadlines. A config read outage produces controlled 503 with zero provider attempts. Recording failures after a valid snapshot preserve the serving outcome. A successful response has `recording_status=degraded` if the final correlated request/invocation transaction failed; successful final repair returns `recorded`. Provider invocation remains one attempt. Cancellation cleanup is bounded best effort, not crash reconciliation.

Only safe routing/generation/outcome metadata is retained. The raw request, response, caller routing key and free-form task type are omitted from rows. Canonical request JSON (sorted keys, compact separators, UTF-8) is HMAC-SHA256 hashed with purpose `content`; routing keys use purpose `routing-key`. A key change breaks digest correlation with earlier rows; routing assignment itself is independent of this secret. Hashes are not anonymization guarantees. Content capture and retention/purge arrive in M4.

Shadow selection is recorded as `selected_execution_deferred`, `not_selected` or `not_applicable`. M3 has no queue or candidate shadow execution. The M4 payload serializes normalized input into an immutable string, pins the full snapshot and has an explicit serialized-size bound. No pending shadow job row is created in M3.

Local operator commands are a trusted process boundary. Separate administrative HTTP authentication and promote/rollback operations remain M7. The factory's explicit `ephemeral=True` mode is only for isolated adapter tests and verification scripts; the module's normal ASGI application always uses PostgreSQL.

## Trade-offs and evidence

No stale-config cache or fallback provider is added. A canary candidate failure is the serving failure. Metadata can be lost during database failure or process termination; degraded events identify known gaps, and later evaluation run manifests will expose missing cases. Readiness checks the database, active snapshot and provider credentials without calling external models.

Migration/repository/fault tests use a dedicated PostgreSQL database whose name ends in `_test`. CI requires that suite; SQLite and mocks do not close migration gates. A fixed 10,000-key corpus establishes allocation tolerance, while bounded API runs prove wiring and persistence. Follow [the M3 plan](../m3-plan.md) for gate evidence.
