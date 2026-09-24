# Security notes

The current Compose ports bind to localhost and `.env` is ignored by Git. `.env.example` contains local demonstration values only. Raw prompt/output capture is planned to be off by default. Provider credentials must be supplied through local environment configuration and must never appear in committed files, logs, metrics, or traces.

Before the chat endpoint is usable, implement client/admin authentication, request limits, safe error mapping, and redaction tests. The full threat and failure checklist is in [the project plan](project-plan.md), sections 14 and 24. The scaffold has a local and CI secret scan; a broader security review remains for the functional implementation.
