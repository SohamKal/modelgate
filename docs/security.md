# Security notes

The current Compose ports bind to localhost and `.env` is ignored by Git. `.env.example` contains local demonstration values only. Raw prompt/output capture is planned to be off by default. Provider credentials must be supplied through local environment configuration and must never appear in committed files, logs, metrics, or traces.

M2 implements a separate gateway bearer key, validated startup settings, request-byte and token limits, bounded serving slots, one-attempt deadlines, safe provider errors, and allowlisted JSON request logs. Validation errors do not echo submitted inputs. Provider bodies and prompts are never logged or stored by the gateway. Uvicorn access logs are disabled in the documented commands and Docker entry point to avoid raw URL/query logging. OpenAI calls explicitly use `store=false`; this is an API storage setting, not a general promise of provider retention behavior.

Provider credentials stay in the ignored environment file or environment variables, never in client requests. The example gateway key is a public localhost demonstration value. Real serving requires a configured provider key and two model IDs; fake tests use synthetic credentials and never call OpenAI.

Groq keys are supplied through `GROQ_API_KEY`, separately from the gateway and OpenAI keys. Groq's adapter omits its unsupported `store` parameter; stateless API support does not establish a general vendor retention policy. Reasoning items and raw outputs are excluded from verification evidence, which records only identifiers, usage and completion metadata. Offline tests never call either real provider.

Admin authentication, rollout authorization, durable audit records, full telemetry redaction checks, and the broader threat review remain for later milestones. The full checklist is in [the project plan](project-plan.md), sections 14 and 24. Local and CI checks scan for secrets and known dependency vulnerabilities; those checks do not establish general production security.
