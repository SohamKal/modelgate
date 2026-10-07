# Gateway API contract

M3 uses immutable registered releases selected through PostgreSQL configuration. The default seed creates `fake-stable` and `fake-candidate`. Names are bounded to 64 ASCII letters/digits/underscores/hyphens; provider identifiers remain `fake`, `openai` or `groq`. M2's fixed release names remain supported by isolated adapter verification tools.

`POST /v1/chat/completions` serves the stable release, or the selected candidate in canary mode. Shadow mode always serves stable. Send `Authorization: Bearer <gateway-key>` and `Content-Type: application/json`. The OpenAPI page at `/docs` includes bearer authorization. The schema is project-specific; it is not a provider SDK compatibility promise.

Example request:

```json
{
  "messages": [{"role": "user", "content": "Classify: I was charged twice."}],
  "task_type": "support_classification",
  "request_key": "demo-case-0042",
  "max_output_tokens": 200
}
```

Messages allow text-only `system`, `user` and `assistant` roles, with 1–32 nonempty messages. `task_type` and `request_key` are optional labels bounded to 64 and 128 characters. Temperature is optional (0–2); null uses a registered release default if present, otherwise omits it upstream. Unsupported temperature fails with 422. Output-token limits are positive integers, default 200, bounded by the configured maximum (default 1,024). Actual body bytes are counted across chunks; the default maximum is 65,536 bytes. Unknown fields, including client model/provider selection and streaming options, are rejected.

Example normalized fake response:

```json
{
  "content": "fake:deterministic-digest",
  "model": "fake-stable-v1",
  "usage": {"input_tokens": 6, "output_tokens": 1, "total_tokens": 7},
  "finish_reason": "stop",
  "request_id": "generated-uuid",
  "release_name": "fake-stable",
  "serving_role": "stable",
  "config_version": 1,
  "recording_status": "recorded"
}
```

This example illustrates fields rather than exact digest/count values. Fake usage is synthetic. Real usage and individual counters can be null when unknown. Completion reasons are `stop`, `length`, `content_filter`, or `unknown`. Refusal text is returned with `content_filter`; an incomplete token-limited result may contain empty text and `length`.

Every HTTP response has a generated `X-Request-ID`, and chat responses/errors contain the matching ID. Incoming request-ID headers do not override generation. A supplied routing key preserves allocation within a configuration version; absent keys use the ingress ID. New versions may change allocation. Repeating a key makes another provider call; it does not deduplicate a completion.

`serving_role` is `stable` or `candidate`. Normal serving has a non-null configuration version. `recording_status=recorded` means correlated metadata committed; `degraded` preserves a successful response when final recording failed. Isolated adapter tools have `config_version=null` and `recording_status=not_applicable`. No raw content is persisted by M3. See [ADR 004](adr/004-persistence-and-routing.md).

Errors have `error.code`, a fixed safe `error.message`, `request_id`, and optional `retry_after_seconds`. No validation input, upstream body or raw exception is echoed. Codes map as follows:

| HTTP status | Codes |
|---|---|
| 401 | `unauthorized` (gateway key); includes `WWW-Authenticate: Bearer` |
| 413 | `request_too_large` |
| 422 | `invalid_request` |
| 429 | `provider_rate_limited`; numeric bounded retry guidance may be supplied |
| 502 | `provider_authentication`, `provider_request_rejected`, `invalid_provider_response` |
| 503 | `serving_busy`, `provider_unavailable`, `configuration_unavailable` |
| 504 | `provider_timeout` |
| 500 | `internal_error` |

Serving makes one attempt. `Retry-After` is guidance to the client, not an automatic retry. Cancellation and timeout release serving capacity; they cannot guarantee an upstream call has stopped.

`GET /health/live` is unauthenticated liveness. `GET /health/ready` checks database access, active configuration and provider credential availability within a bounded deadline; it never calls a real model. `/metrics/` exposes default process metrics on the localhost-scoped deployment. Administrative HTTP APIs arrive in M7. M3 shadow selection is persisted as `selected_execution_deferred`, `not_selected` or `not_applicable`; there is no queue, candidate call or evaluation until M4.
