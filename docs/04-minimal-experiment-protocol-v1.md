# Minimal Experiment Protocol v1

**Date**: 2026-10-22  
**Track**: AIStudioOS-Grok  
**Status**: Locked for Phase 1 execution

## 1. Objective

Prove that a single AI Manager + single Worker, governed by an independent Control Plane, can run a closed **Observe → Plan → Execute → Verify → Decide** loop with:

1. Autonomous next-task generation from goal gap  
2. Independent verification (accept / reject)  
3. Recovery after forced process kill  
4. Hard budget & permission enforcement (not prompt-based)

## 2. Success Criteria (all must pass)

| # | Capability | Pass Condition |
|---|------------|----------------|
| 1 | Task Generation | System proposes ≥1 concrete, verifiable task from the high-level goal without human writing the task |
| 2 | Execute + Verify | Worker produces artifact; Independent Verifier accepts or rejects with structured feedback; rejection leads to re-proposal |
| 3 | Recovery | Force-kill mid-execution; on restart system resumes from last checkpoint; previously ACCEPTED work is not lost |
| 4 | Governance | When estimated or actual cost would exceed budget, or when a denied action (git_push / network / delete) is requested, system **hard-stops** and enters BLOCKED; only human CLI can raise budget or change policy |

## 3. Scope (intentionally tiny)

- 1 Goal  
- 1 Manager role (can be a simple LLM call or scripted proposer for the first run)  
- 1 Worker role (coding)  
- Budget hard limit: **$5 USD** (or equivalent token budget)  
- Max continuous run target: 2–4 hours for first validation (stretch to 24h later)  
- No dynamic team formation  
- No multi-project  

## 4. Concrete Experiment Target: Exp-01 Tiny Word-Count CLI

**Goal title**: Build a tiny word-count CLI  

**Description**:  
Create a pure-Python command-line tool `wcmini` that:

- Accepts one or more file paths  
- Prints line count, word count, and byte count (similar to `wc`)  
- Has a `--help` flag  
- Ships with at least 5 unit tests that pass  

**Acceptance criteria** (must all be true for goal completion):

1. `python -m wcmini --help` exits 0 and shows usage  
2. Running on a known fixture file produces correct line/word/byte counts  
3. At least 5 pytest tests exist and all pass  
4. Code lives under `experiments/exp01-tiny-cli/workspace/`  
5. No network calls and no git push are performed during the run  

**Why this target**:  
- Fully self-contained  
- Automatically verifiable by tests  
- Small enough to finish inside a tight budget  
- Exercises file write, shell (pytest), and permission boundaries  

## 5. Architecture for the Experiment

```
Human (founder)
    │
    ▼
Control Plane  (this repo: control_plane/)
    │  owns: Goal, Task queue, Budget, Permission Policy, Checkpoints
    │
    ├── Manager (proposes next task only)
    │
    ├── Worker  (executes approved task inside sandbox)
    │
    └── Independent Verifier  (runs tests / checks criteria; never the same process as Worker)
```

**Hard rules**:

- Manager never directly changes task status to ACCEPTED.  
- Worker never decides its own success.  
- Budget and permissions are checked inside Control Plane before and after execution.  
- Every status transition is checkpointed.

## 6. Metrics to Record

Exactly the unified dual-track metrics:

- Autonomous Task Completion Rate  
- Continuous Effective Runtime  
- Human Interventions per 24h  
- Fault Recovery Capability  
- Cost per Accepted Task  
- Permission & Safety Control (violation attempts)  
- Actual Deliverable Quality  

## 7. Execution Steps (for the human operator)

1. `python -m pytest tests/test_control_plane.py -v`  → confirm Control Plane unit tests pass  
2. Create the goal via a short Python script or future Manager  
3. Let Manager propose the first task  
4. Control Plane auto-approves or human approves via CLI  
5. Worker runs (initially can be manual / scripted; later OpenHands)  
6. Verifier runs pytest + acceptance checks  
7. Force-kill and restart to validate recovery  
8. Attempt a budget-exceeding task and a forbidden action to validate hard stops  
9. Record metrics in `experiments/exp01-tiny-cli/results.md`

## 8. Out of Scope for Exp-01

- Multi-agent collaboration  
- Dynamic role hiring  
- Long-running 72h unattended operation  
- Real LCS-Watcher integration (kept for a later experiment)  
- Temporal / DBOS (add after the loop is proven)

---

This protocol is now the binding reference for Phase 1 on the Grok track.
