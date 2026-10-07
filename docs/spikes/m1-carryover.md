# M1 technical spikes carried into M2

Audit and implementation date: October 5, 2026. The M1 commit contained placeholders and only a liveness test. Provider normalization, deadlines/cancellation, nonblocking admission, and application trace export had no completion evidence.

## Normalization — offline verified

**Question:** Can one contract represent Responses output without exposing vendor-specific payloads?

**Prediction:** Text, completion status and supplied token counters can be mapped; unsupported or missing fields need explicit treatment.

**Experiment:** Feed synthetic Responses fixtures through the adapter's normalization function and through actual local HTTP. Exercise reasoning items, absent/partial usage, malformed fields, refusals, truncation and inconsistent counts.

**Observed result:** Assistant text is extracted; reasoning and usage breakdown details are excluded. Unknown counters remain null. Invalid schemas or inconsistent supplied totals become `invalid_provider_response`. Refusals and token exhaustion retain explicit completion reasons.

**Decision:** Keep upstream schema handling inside the OpenAI adapter; expose nullable usage and `stop`, `length`, `content_filter` or `unknown` completion reasons. Fake usage is synthetic and not evidence of real token cost.

**Source:** [OpenAI Responses reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create), checked October 5, 2026. The implementation uses the repository's locked HTTPX and Pydantic packages.

## Timeouts and cancellation — offline verified

**Question:** Does an async serving deadline stop waiting promptly without retrying or leaking local resources?

**Prediction:** A total `asyncio.timeout` around one HTTPX invocation should cancel a delayed provider call and preserve external cancellation.

**Experiment:** Start a real loopback TCP server that delays its response by ten seconds. Apply a 0.1-second serving deadline, separately cancel a started call, and require return within a generous one-second test bound. Assert one upstream request and a closed HTTP client. API tests also verify serving capacity is restored after cancellation and timeout.

**Observed result:** Both calls terminate promptly. Test-server teardown initially waited for its delayed connection before cancelling handlers; closing/cancelling handlers before awaiting server shutdown resolves that fixture delay.

**Decision:** Use one lifespan-managed client and one serving attempt. Propagate `CancelledError`; map deadline expiry to a safe 504. Cancelling local waiting cannot guarantee the upstream has stopped processing or billing a request.

**Source:** Locked Python 3.12 `asyncio` and HTTPX behavior, verified at the actual HTTP boundary. Further retry policy belongs to the shadow worker milestone.

## Queue admission — offline verified

**Question:** Can full-queue admission avoid blocking a serving request?

**Prediction:** `put_nowait` on a full bounded `asyncio.Queue` raises `QueueFull` immediately.

**Experiment:** Fill a one-slot queue, attempt a second admission, and await an independently scheduled fake serving call with a one-second safety bound.

**Observed result:** The extra copy is rejected; the accepted job stays in the queue and serving finishes successfully.

**Decision:** M4 should use nonblocking admission and counted skip outcomes. This experiment makes no durability, worker supervision, or production shadow-isolation claim.

**Source:** Python 3.12 `asyncio.Queue`, exercised directly.

## Trace export — verified through Collector and Jaeger

**Question:** Can the pinned OpenTelemetry exporter send a span through the configured Collector to Jaeger?

**Prediction:** A synthetic span can be flushed over OTLP/gRPC and queried through Jaeger's API.

**Experiment prepared:** `scripts.trace_spike` creates one `m2.trace_export` span, flushes and shuts down its local tracer provider, and polls Jaeger for that exact trace ID and span name. It reports `verified` only when the span is retrieved. The Collector's OTLP port is published on localhost for this command.

**Observed result:** Docker Desktop was started, the pinned Collector/Jaeger services were launched, and the actual exporter sent the span through the Collector. Jaeger's API returned the matching operation and trace ID. [Trace evidence](trace-evidence.json) records `status=verified` and trace ID `c9390a70c000b1d5a5e535f53169524d`. Unit tests separately cover positive and missing retrieval outcomes.

**Decision:** Close M2.0d based on actual export and retrieval evidence. Preserve the standalone verification command. Full application instrumentation remains in M6.

**Estimate revision:** All four experiments now have runtime evidence. Live model access remains the external prerequisite for M2 completion. The original 18–24 hour estimate remains a budget, not measured elapsed work; budget remaining verification after the credentials and accessible model IDs are configured.
