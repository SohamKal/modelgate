"""M2.0d: export a synthetic span, then verify it through Jaeger's API."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


async def retrieve_trace(
    trace_id: str,
    jaeger_url: str,
    seconds: float = 15,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    deadline = time.monotonic() + seconds
    async with httpx.AsyncClient(timeout=2, trust_env=False, transport=transport) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"{jaeger_url.rstrip('/')}/api/traces/{trace_id}")
                if response.status_code == 200:
                    payload = response.json()
                    traces = payload.get("data", [])
                    if any(
                        span.get("operationName") == "m2.trace_export"
                        and span.get("traceID", "").lower() == trace_id
                        for trace in traces
                        for span in trace.get("spans", [])
                    ):
                        return True
            except (httpx.HTTPError, ValueError, AttributeError, TypeError):
                pass
            await asyncio.sleep(0.25)
    return False


async def verify(otlp_endpoint: str, jaeger_url: str) -> dict[str, object]:
    provider = TracerProvider(resource=Resource.create({"service.name": "modelgate-spike"}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True, timeout=3))
    )
    try:
        with provider.get_tracer("modelgate.spike").start_as_current_span(
            "m2.trace_export", attributes={"spike.synthetic": True}
        ) as span:
            trace_id = f"{span.get_span_context().trace_id:032x}"
        flushed = provider.force_flush(timeout_millis=5000)
        found = flushed and await retrieve_trace(trace_id, jaeger_url)
        return {"gate": "M2.0d", "status": "verified" if found else "pending", "trace_id": trace_id}
    finally:
        provider.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otlp-endpoint", default="http://127.0.0.1:4317")
    parser.add_argument("--jaeger-url", default="http://127.0.0.1:16686")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = asyncio.run(verify(args.otlp_endpoint, args.jaeger_url))
    except Exception:
        print(
            "Trace verification could not run. Check Collector and Jaeger availability.",
            file=sys.stderr,
        )
        return 2
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n")
    return 0 if report["status"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
