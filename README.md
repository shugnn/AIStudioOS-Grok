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

## Current Status (2026-10-31)

**P0 isolated loop** — host evidence in-repo; **production 7×24 NOT ACCEPTED**.

| Area | Status |
|------|--------|
| Control Plane | Goal/Task/Budget/Permission/Checkpoint |
| L1 Runner | fcntl + msvcrt; schtasks ≥3; **emergency stop** (exit 3) |
| Soak metrics | with_work/idle; finally + checkpoint; **`--max-wall-seconds`** |
| 24h observation | **PARTIAL** 1330/1440; with_work 1264 — see `docs/progress/soak_2h/metrics.json` |
| Evidence | `EVIDENCE_PACKAGE.md` · `DUAL_TRACK_MATRIX.md` · Issue #9 |

Do not cite historical 2h `ok=120/120` as business 120 (idle majority).

## Quick Start

```bash
# Fast health check (Windows: py -3)
PYTHONPATH=. python scripts/health_check.py

# Unit tests
PYTHONPATH=. python -m pytest tests/ -q

# Short honest soak
PYTHONPATH=. python scripts/soak_2h.py --cycles 10 --interval 2 --via-l1 --idle-policy stop

# Bounded ~24h wall (example; needs founder host time)
# PYTHONPATH=. python scripts/soak_2h.py --cycles 2000 --interval 60 --via-l1 --seed 300 \
#   --idle-policy reseed --max-wall-seconds 86400

# Emergency stop
# echo stop > docs/progress/EMERGENCY_STOP
```

## Key Documents

| Doc | Description |
|-----|-------------|
| `docs/progress/P0_STATUS.md` | One-page P0 snapshot |
| `docs/progress/DUAL_TRACK_MATRIX.md` | Grok vs ChatGPT gates |
| `docs/progress/EVIDENCE_PACKAGE.md` | Evidence layout |
| `docs/progress/soak_metrics_policy.md` | Effective vs idle |
| `docs/progress/EMERGENCY_STOP.md` | Kill switch procedure |
| Issue #9 | P0 acceptance & evidence |

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
L1 Runner (scripts/l1_runner.py) — OS lock, scheduled wake, emergency stop
```

Manager never decides acceptance. Budget & permissions are enforced in code, not only by prompts.
