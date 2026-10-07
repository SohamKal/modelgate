# Changelog

## Unreleased

- Added M3 PostgreSQL migrations, immutable releases/configuration history, atomic activation audit, repeatable seed and local configuration CLI.
- Added deterministic canary serving and independent shadow selection, durable configuration metadata and safe invocation records.
- Preserved successful responses during recording failures; added bounded DB readiness/deadlines, pinned snapshots and PostgreSQL CI/fault tests.
- Added routing rehearsal/evidence and Docker startup that migrates and seeds before serving. Shadow execution remains M4 work.

- Added Groq Responses support and provider-selectable verification; both GPT-OSS model configurations passed the live gate on October 7, 2026.
- Fixed normalization of provider reasoning-text items, which are discarded before assistant-content parsing. Groq requests omit its unsupported storage parameter.

- Implemented the authenticated stable chat endpoint, deterministic fake provider, and OpenAI Responses adapter with two environment-selected model configurations.
- Added request IDs, validated settings, actual request-byte limits, output-token/concurrency bounds, one-attempt deadlines, safe error mapping, and allowlisted request logs.
- Added offline contract/API tests and real local HTTP timeout/cancellation experiments, plus trace-export and live-model verification commands.
- Recorded M2 subphases and verified all four M1 carryover spikes, including actual Collector-to-Jaeger export/retrieval. Live model access remains a completion gate.

- Created the project foundation: package layout, tooling, Compose services, observability configuration, documentation, and the full project plan.

Functional release notes will start with the first stable gateway slice.
