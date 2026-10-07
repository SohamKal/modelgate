# ADR 002: Stable text contract and provider adapters

**Status:** Accepted for M2 implementation  
**Date:** 2026-10-05

## Context and decision

Clients need one small text-only contract across fake and real models. M2 uses Pydantic contracts, an async provider protocol, and one stable serving call. Request IDs are generated at ingress. Release selection belongs to startup configuration; request keys do not deduplicate paid calls. Durable version identifiers remain null until M3.

The OpenAI adapter uses the Responses API via HTTPX with `store=false`, synchronous nonstreaming requests, a bounded response body, and no serving retries. OpenAI recommends Responses for new projects in its [official guide](https://developers.openai.com/api/docs/guides/migrate-to-responses). The adapter parses output items into assistant text and controlled completion reasons; token usage remains nullable. Unsupported content/tool shapes become safe provider errors.

Two releases, `openai-a` and `openai-b`, use distinct environment-supplied model IDs through the same adapter. Temperature support is explicitly configured per release; null temperature is omitted upstream. The default is the deterministic fake adapter with synthetic usage.

## Consequences

Clients can switch serving releases without changing their endpoint or body. The gateway schema is project-specific and does not promise provider SDK compatibility. A total deadline includes one call and normalization. Provider authorization failures return 502 while invalid client credentials return 401. Normalized error messages and allowlisted JSON request logs exclude prompts, keys and raw provider exceptions. Full rollout history and shadow behavior remain separate milestones.
