# API contract notes

The full proposed public and administrative contracts are in [the project plan](project-plan.md), section 11. Only `GET /health/live` and Prometheus `/metrics/` exist in the scaffold.

The first functional slice will add `POST /v1/chat/completions` with a small normalized request and response schema. The planned request is:

```json
{
  "messages": [{"role": "user", "content": "Classify: I was charged twice."}],
  "task_type": "support_classification",
  "request_key": "demo-case-0042",
  "max_output_tokens": 200,
  "temperature": 0
}
```

The `request_key` will control deterministic routing within one configuration version. It will not deduplicate requests or prevent another provider charge. Shadow responses will never be returned to the client. Authentication, safe error shapes, readiness, and administrative release endpoints remain to be implemented before this API is presented as usable.
