# AIStudioOS-Grok

**Independent track of AI Studio OS**  
Lead: Grok  
Parallel track: [AIStudioOS-ChatGPT](https://github.com/shugnn/AIStudioOS-ChatGPT)

## Mission

以人类创始人为最终决策者，AI Agent 在权限与预算约束下自主组织、执行、验证、迭代；长期持续运行是目标，**须证据验收，禁止口头宣称**。

## Dual-Track Principles

- Independent tech choices; separate repos
- Same high-level goal; comparable metrics
- Important decisions via GitHub Issue/PR
- Zero new paid spend by default; local host first

**GitHub**: https://github.com/shugnn/AIStudioOS-Grok

## Current Status (2026-10-29)

**P0 isolated loop (FOUNDER-20261024-AUTOLOOP)** — engineering evidence on host; **production 7×24 NOT ACCEPTED**.

| Area | Status |
|------|--------|
| Control Plane | Goal/Task/Budget/Permission/Checkpoint |
| L1 Runner | fcntl + **msvcrt** lock; schtasks ≥3 PASS |
| Soak metrics | `cycles_with_work` / idle required (`scripts/soak_2h.py`) |
| CP state path | `docs/progress/exp02_auto_loop/state/` (not `/tmp`) |
| Evidence layout | `docs/progress/EVIDENCE_PACKAGE.md` |
| Final matrix | [Issue #9](https://github.com/shugnn/AIStudioOS-Grok/issues/9) |
| 24h soak | **NOT STARTED** |

Historical 2h wall-clock: process exit 120/120, **~34 effective** work cycles (idle rest). Do not cite as business 120.

## Quick Start

```bash
# Control Plane unit tests
PYTHONPATH=. python -m pytest tests/test_control_plane.py -v

# One CP cycle
PYTHONPATH=. python experiments/exp02_auto_loop/cp_driven_loop.py --reset --once

# Short via-L1 soak with honest metrics (Windows: py -3)
PYTHONPATH=. python scripts/soak_2h.py --cycles 10 --interval 2 --via-l1 --idle-policy stop

# Evidence hashes
PYTHONPATH=. python scripts/evidence_sha256sums.py docs/progress/soak_2h
```

## Key Documents

| Doc | Description |
|-----|-------------|
| `docs/progress/EVIDENCE_PACKAGE.md` | Evidence dirs, metrics, binding strength |
| `docs/progress/soak_metrics_policy.md` | Effective vs idle cycles |
| `docs/06-l1-runner-design.md` | L1 lock / jobs |
| `docs/05-cross-team-communication-protocol.md` | Cross-track protocol |
| `docs/j-exp01-cross-track-ack.md` | Proposed minimal joint experiment (design only) |
| Issue #9 | P0 acceptance matrix & host evidence |

## Architecture (thin)

```
Human Founder
    │
    ▼
Control Plane  (control_plane/)
  - Goal / Task queue
  - Hard Budget envelope
  - Hard Permission policy
  - Durable Checkpoints
    │
    ├── Manager   (proposes only)
    ├── Worker    (executes approved work)
    └── Verifier  (independent accept/reject)
    │
L1 Runner (scripts/l1_runner.py) — OS lock, scheduled wake
```

Manager never decides acceptance. Budget & permissions are enforced in code, not only by prompts.
