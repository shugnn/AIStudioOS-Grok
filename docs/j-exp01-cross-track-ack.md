# J-Exp-01 — Cross-track ACK once (design only)

**Status**: Proposed in ACGK review (Issue #8). **Not authorized for implementation** until founder approves.

## Goal

One bounded handoff: Grok creates a `request_id` task in local store → projects a comment to ChatGPT Issue → ChatGPT Runner **read-only** ACKs with evidence path → Grok Verifier checks fields + SHA.

## Non-goals

- No modify ChatGPT application code from Grok
- No paid APIs / Actions minutes
- No main-merge requirement
- Not a substitute for OS scheduler or 24h soak

## Minimal fields

```
request_id, from_track, to_track, created_at, due_at,
status: NEW|ACK|WORKING|BLOCKED|VERIFYING|DONE|FAILED,
idempotency_key, evidence_urls[], sha, human_required: bool
```

## Acceptance (if later approved)

1. Exactly one NEW→ACK→DONE path for a fixed `idempotency_key`
2. Replay does not create a second DONE
3. Evidence links resolve; SHA matches declared head
4. $0; both tracks document UNVERIFIED items honestly

## Risks

- ChatGPT write access to Grok Issues may still be limited
- Treating GitHub comments as sole state store (avoid; local store is source of truth)

## Owner

Design: Grok. Execution: only after FOUNDER ACK on Issue #8 or a dedicated Issue.
