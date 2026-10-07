# M3 implementation review

Review evidence below comes from code inspection, offline provider tests, real PostgreSQL tests, and the actual HTTP rehearsal. It is available for author sign-off; it does not claim a separate human review has occurred.

| Subphase | What to explain | Evidence and failure behavior |
|---|---|---|
| M3.0 | Why configuration and credential sources are separate | ADR 004; PostgreSQL controls routing, environment controls credentials, requests cannot pick providers. Hashes replace retained free-form input. |
| M3.1 | Why migrations/constraints need real PostgreSQL | Initial revision and `test_persistence.py`; upgrade/downgrade/re-upgrade/check succeed. Invalid weights fail at DB boundary, and immutable row triggers reject mutation. |
| M3.2 | Why activation cannot publish partial history | Active-pointer row lock and expected-version check; audit/config/pointer share one transaction. Injected PostgreSQL audit rejection rolls everything back; one concurrent activation wins. Seed preserves active history. |
| M3.3 | What determinism does and does not promise | Fixed SHA-256 encoding/vectors and purpose separation, 0/100/threshold tests, process restart calculation, 10,000-key corpus. Keys route consistently within a version and never deduplicate provider calls. |
| M3.4 | Why recording failure does not invalidate content | Request/outcome writes have short bounded transactions; final write can repair an initial failure. Failed final recording returns degraded success. No transaction spans an upstream call. Failed config resolution returns 503 before invocation. |
| M3.5 | Why a canary failure reaches the client | Candidate is the chosen serving release. No stable fallback or second attempt exists. Pinned-snapshot tests activate a new version mid-call and verify the original call's metadata stays unchanged. |
| M3.6 | Why selected shadow work is not a completed comparison | Selection is explicitly execution-deferred; actual HTTP results show no candidate serving in shadow modes. Payload serialization prevents input mutation and enforces a size bound. M4 still needs queue/consumers/outcome accounting. |
| M3.7 | What the failure tests prove | Real PostgreSQL insert rejection, division-error read faults, stalled queries, transaction rollback, cancellation and metadata repair. Synthetic HTTP fixtures cover both real adapter registries without external calls. CI requires PostgreSQL. |
| M3.8 | What remains to close the milestone | Documentation, fake HTTP evidence and container startup supplied; implementation committed locally as `caa5a23`. The author chose to defer publication/remote CI. Author sign-off remains pending. |

## Known limits

- Database outages stop configuration resolution; no cached fallback is offered.
- Detected recording loss is logged and marked degraded; crash history and missing evaluation cases are not reconciled by M3.
- Trusted local CLI access precedes separately authenticated HTTP administration.
- No retained content, retention purge, queue, candidate shadow invocation or evaluator exists yet.
- Statistical evidence uses pure routing over 10,000 keys. The smaller HTTP batch validates persistence and wiring, rather than establishing its own 10% statistical tolerance.
