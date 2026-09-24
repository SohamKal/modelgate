# ADR 001: Modular monolith with bounded in-process shadow consumers

**Status:** Accepted for the initial portfolio release  
**Date:** 2026-09-21

## Context

The project needs a stable client request path and asynchronous candidate evaluation. The initial deployment boundary is one gateway process on one Docker Compose host. A durable broker would add operational and delivery-semantics work before the core behavior is proven.

## Decision

Keep the gateway, routing, and shadow consumers in one Python process. Separate modules by responsibility. Use a bounded `asyncio.Queue`, fixed consumer count, and nonblocking admission. Pin release and configuration IDs on each accepted job. The client waits only for the serving provider.

## Consequences

The system is easier to start and reason about locally. A full queue must skip and count shadow work without delaying serving. Unfinished work can be lost on restart; report interrupted and missing comparisons, and make no durability claim. Multiple gateway replicas and durable recovery are outside the initial release. A future broker migration requires explicit delivery and deduplication semantics.
