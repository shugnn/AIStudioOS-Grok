# L1 Minimal Runner Design (Grok Track)

**request_id**: XTEAM-20261023-01  
**Status**: Design + isolated local validation  
**Constraint**: zero new paid services, no production deploy, no GitHub Actions unless founder approves

## Goals

Prove a process can periodically **wake → observe → select → lock → act (safe) → verify → checkpoint → report** without:

- LLM spend (default budget $0 for L1 acts)
- Duplicate side effects on re-entry
- Infinite empty loops
- Expanding permissions

## Architecture

```
cron/manual
    │
    ▼
l1_runner.py
    │  file lock (fcntl / lockfile)
    ▼
observe: list open issues both repos (read-only API)
select:  only eligible local jobs (heartbeat | dry_metrics_fill)
lock:    exclusive lockfile; skip if held
execute: allowed actions only
verify:  independent checks (files exist, JSON valid, no forbidden actions attempted)
checkpoint: write docs/progress/runner-*.json
report:  optional git-friendly artifact (no auto-push required)
```

## Parameters (defaults)

| Param | Value | Rationale |
|-------|-------|-----------|
| Trigger | manual or local cron | No Actions cost |
| Frequency | ≤ 1/hour recommended | Avoid API rate noise |
| Lock TTL | 10 minutes | Crash recovery |
| Max jobs/run | 1 | Simplicity |
| Budget | $0 | Hard |
| Network | GitHub API only (token) | Existing PAT |
| Retries | 0 for side-effecting acts in L1 | Idempotent keys instead |
| Human gate | any job needing spend/write-to-foreign-repo | BLOCKED |

## Eligible jobs (whitelist)

1. `heartbeat` — run `l1_heartbeat.py` logic; write timestamped JSON
2. `dry_protocol_check` — validate local protocol schema files exist
3. *(future, gated)* `exp_repro` — re-run Exp-01 only if explicitly enabled via env `AISTUDIO_ALLOW_EXP_REPRO=1`

## Idempotency

- Each run has `run_id` = UTC timestamp + random suffix
- Heartbeat path includes timestamp → natural unique artifacts
- Lock prevents concurrent double execution
- Job key `job:heartbeat:YYYYMMDDHH` — at most one success per hour window (optional soft dedup)

## Crash / force-kill recovery

1. Lockfile contains pid + start time
2. If lock held but pid dead → treat as stale, acquire
3. Partial JSON write uses temp + rename (same as FileStore)
4. Proof: kill -9 mid-run → next run still succeeds and does not duplicate hourly key if implemented

## What this is NOT

- Not continuous autonomous R&D
- Not LLM Manager
- Not authorized to comment on every issue automatically (commenting is optional and rate-limited)

## Acceptance for XTEAM-20261023-01

- [x] Design doc
- [ ] Runner script runs twice with lock
- [ ] Force-kill mid-run then recover
- [ ] Logs + commit SHA


## Implementation status (post ChatGPT P0 review)

| Item | Status |
|------|--------|
| Atomic lock `O_CREAT\|O_EXCL` | **Implemented** in `scripts/l1_runner.py` |
| No TTL-preempt of live PID | **Implemented**; stale only if PID dead |
| Owner token on release | **Implemented** |
| Failed job → non-zero exit | **Implemented** |
| max_jobs default 1 | **Implemented** (`--max-jobs`) |
| Hourly job key dedup | **Not implemented** (documented as future) |
| OS fcntl advisory lock | **Not used**; O_EXCL file create instead |
| Scheduled cron evidence | **Manual / external cron only**; no Actions |



## Lock model (updated 2026-10-24)

**Mutual exclusion source: OS fcntl.flock(LOCK_EX) on an open fd.**

- Process alive + fd open -> lock held by kernel
- Process exit / kill -9 -> kernel closes fd -> lock released automatically
- No pid-file stale reclaim (avoids non-atomic unlink/recreate double-owner race)
- Lock file path is only a rendezvous name; existence of the file is not the lock
- Metadata (pid, token) in the file is for debugging only

Verified: concurrent second process -> lock_held; kill -9 -> next run acquires.


## Ops constraints (fcntl lock)

1. **Platform**: Linux/macOS only for L1. Windows needs a separate lock backend.
2. **Never delete or replace** `docs/progress/.l1_runner.lock` while runners may be active (cleanup scripts, deploy). File is rendezvous only; deleting it does not drop an existing flock on an open fd and can confuse operators.
3. **Exit codes**: `0` = executed ok; `1` = executed but job failed; `2` = skipped (`lock_held`, not executed).
4. **NFS/shared FS**: not in acceptance scope.
5. Automated regression: `python scripts/test_l1_runner_lock.py`
