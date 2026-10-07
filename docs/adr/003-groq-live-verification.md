# ADR 003: Groq for free development verification

**Status:** Accepted and verified live  
**Date:** 2026-10-07

The author chose a free development route. Use Groq's free-plan `openai/gpt-oss-20b` and `openai/gpt-oss-120b` configurations to close M2's real-model gate. The original plan permits two real configurations on one vendor; OpenAI support remains available.

Groq's [Responses API](https://console.groq.com/docs/responses-api) lists `store` as unsupported and returns separate reasoning-text items. Its request builder omits storage/background parameters and sends low reasoning effort for GPT-OSS. It reuses bounded transport, safe errors, one serving attempt and response normalization. Reasoning content is discarded before assistant-text parsing.

The CLI supports `--provider groq` and `MODELGATE_VERIFICATION_PROVIDER`; it validates both releases before either request. Groq checks allow up to 512 output tokens, bounded by the gateway's configured limit, and require completed nonempty text with the expected model ID, release and stable role. There is no automatic retry or provider fallback.

Both requests succeeded on October 7, 2026. [Evidence](../spikes/model-evidence.json) records safe identifiers, token usage and completion status, excluding keys, response bodies and reasoning. Free-plan [quotas](https://console.groq.com/docs/rate-limits) apply per account.

Default application serving remains fake; the verification provider is independent of ordinary serving. The existing Docker/trace evidence predates this adapter; a subsequent image build includes it. CI and author review remain separate completion gates.
