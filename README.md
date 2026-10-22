# AIStudioOS-Grok

**Independent track of AI Studio OS**  
Lead: Grok  
Parallel track: AIStudioOS-ChatGPT (led by ChatGPT)

## Mission

建立一个以人类创始人为最终决策者，以 AI Agent 为主要生产力，能够自主组织、自主执行、自主验证、自主迭代，并可长期持续运行的智能工作室操作系统。

## Dual-Track Principles

- Independent technology choices and architecture
- Separate repositories and experiment data
- Same high-level goal
- Unified evaluation metrics for later objective comparison
- Possibility of integrating proven components later

**GitHub**: https://github.com/shugnn/AIStudioOS-Grok

## Current Status (2026-10-22)

**Phase 1: Thin Control Plane + Minimal Experiment**

- [x] Technical Investigation Report v0.1
- [x] Dual-track alignment & unified metrics
- [x] Minimal Experiment Protocol v1 (locked)
- [x] Thin Control Plane prototype (Goal / Task / Budget / Permission / Checkpoint)
- [x] Unit tests for Control Plane (6/6 passed)
- [ ] Run Exp-01 (Tiny Word-Count CLI) closed loop
- [ ] Record metrics & recovery test

## Quick Start

```bash
# Run Control Plane unit tests
PYTHONPATH=. python -m pytest tests/test_control_plane.py -v

# Inspect Control Plane status (after a goal is created)
PYTHONPATH=. python -m control_plane.cli status
```

## Key Documents

| Doc | Description |
|-----|-------------|
| `docs/01-technical-investigation-report.md` | Evidence-based evaluation of 7 candidate technologies |
| `docs/03-dual-track-and-evaluation-metrics.md` | Parallel R&D rules + unified metrics |
| `docs/04-minimal-experiment-protocol-v1.md` | Binding protocol for Phase 1 experiment |
| `experiments/exp01-tiny-cli/` | First concrete experiment target |

## Architecture (Phase 1)

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
```

Manager never decides acceptance. Budget & permissions are enforced in code, not only by prompts.
