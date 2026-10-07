# M2 API contract

Server-selected releases are `fake`, `openai-a`, `openai-b`, `groq-a` and `groq-b`. All use the same public request and response contract. See [Groq verification evidence](spikes/model-evidence.json) and [ADR 003](adr/003-groq-live-verification.md).

`POST /v1/chat/completions` serves one configured stable release. Send `Authorization: Bearer <gateway-key>` and `Content-Type: application/json`. The OpenAPI page at `/docs` includes bearer authorization. The schema is project-specific; it is not a provider SDK compatibility promise.

Example request:

```json
{
  "messages": [{"role": "user", "content": "Classify: I was charged twice."}],
  "task_type": "support_classification",
  "request_key": "demo-case-0042",
  "max_output_tokens": 200
}
```

Messages allow text-only `system`, `user` and `assistant` roles, with 1–32 nonempty messages. `task_type` and `request_key` are optional labels bounded to 64 and 128 characters. Temperature is optional (0–2); null omits it upstream. Unsupported temperature fails with 422. Output-token limits are positive integers, default 200, bounded by the configured maximum (default 1,024). Actual body bytes are counted across chunks; the default maximum is 65,536 bytes. Unknown fields, including client model/provider selection and streaming options, are rejected.

Example normalized fake response:

```json
{
  "content": "fake:deterministic-digest",
  "model": "fake-v1",
  "usage": {"input_tokens": 6, "output_tokens": 1, "total_tokens": 7},
  "finish_reason": "stop",
  "request_id": "generated-uuid",
  "release_name": "fake",
  "serving_role": "stable",
  "config_version": null
}
```

This example illustrates fields rather than exact digest/count values. Fake usage is synthetic. Real usage and individual counters can be null when unknown. Completion reasons are `stop`, `length`, `content_filter`, or `unknown`. Refusal text is returned with `content_filter`; an incomplete token-limited result may contain empty text and `length`.

Every HTTP response has a generated `X-Request-ID`, and chat responses/errors contain the matching ID. Incoming request-ID headers do not override generation. A routing key has no deduplication guarantee. Deterministic routing and durable configuration versioning begin in M3.

Errors have `error.code`, a fixed safe `error.message`, `request_id`, and optional `retry_after_seconds`. No validation input, upstream body or raw exception is echoed. Codes map as follows:

| HTTP status | Codes |
|---|---|
| 401 | `unauthorized` (gateway key); includes `WWW-Authenticate: Bearer` |
| 413 | `request_too_large` |
| 422 | `invalid_request` |
| 429 | `provider_rate_limited`; numeric bounded retry guidance may be supplied |
| 502 | `provider_authentication`, `provider_request_rejected`, `invalid_provider_response` |
| 503 | `serving_busy`, `provider_unavailable` |
| 504 | `provider_timeout` |
| 500 | `internal_error` |

Serving makes one attempt. `Retry-After` is guidance to the client, not an automatic retry. Cancellation and timeout release serving capacity; they cannot guarantee an upstream call has stopped.

`GET /health/live` is unauthenticated liveness. `GET /health/ready` reports initialized local serving resources without an upstream or database call. `/metrics/` exposes default process metrics on the localhost-scoped deployment. Administrative APIs, persistence, canary, and shadow execution remain in later milestones; their proposed contracts are in [the project plan](project-plan.md), section 11.
