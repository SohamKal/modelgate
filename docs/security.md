# Security notes

The current Compose ports bind to localhost and `.env` is ignored by Git. `.env.example` contains local demonstration values only. M3 has no raw content capture. Provider credentials must be supplied through local environment configuration and must never appear in committed files, logs, metrics, or traces.

M2 implements a separate gateway bearer key, validated startup settings, request-byte and token limits, bounded serving slots, one-attempt deadlines, safe provider errors, and allowlisted JSON request logs. Validation errors do not echo submitted inputs. Provider bodies and prompts are never logged or stored by the gateway. Uvicorn access logs are disabled in the documented commands and Docker entry point to avoid raw URL/query logging. OpenAI calls explicitly use `store=false`; this is an API storage setting, not a general promise of provider retention behavior.

Provider credentials stay in the ignored environment file or environment variables, never in client requests or release rows. The example gateway/hash keys are public localhost demonstration values. Normal serving uses registered model definitions and the selected provider key; isolated two-model verification additionally requires its two model settings. Fake tests use synthetic credentials and never call real providers.

Groq keys are supplied through `GROQ_API_KEY`, separately from the gateway and OpenAI keys. Groq's adapter omits its unsupported `store` parameter; stateless API support does not establish a general vendor retention policy. Reasoning items and raw outputs are excluded from verification evidence, which records only identifiers, usage and completion metadata. Offline tests never call either real provider.

M3 uses short transactions, hidden SQL parameters, bounded database deadlines, immutable history guards and atomic activation audit records. Stored request content/routing-key digests use HMAC-SHA256 with a separate environment key; digest correlation changes when that key rotates. Hashes do not guarantee anonymity. Raw free-form task labels are not retained. A local CLI requires access to the host/database environment; it is not a remotely authenticated administration API.

Separate admin authentication, rollout authorization, full telemetry redaction checks, retention/purge and the broader threat review remain for later milestones. The full checklist is in [the project plan](project-plan.md), sections 14 and 24. Local and CI checks scan for secrets and known dependency vulnerabilities; those checks do not establish general production security.
