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

Suggested GitHub repository: **shugnn/AIStudioOS-Grok**

## Current Phase (2026-10-22)

**Technical Investigation → Minimal Experiment Design**

- [x] Project structure initialized
- [x] Technical Investigation Report v0.1 (7 candidate technologies)
- [x] Minimal Experiment Protocol draft
- [x] Dual-track alignment & unified metrics documented
- [ ] Finalize experiment target task
- [ ] Implement thinnest Control Plane (Goal / Task / Budget / Permission / Checkpoint)
- [ ] Run first closed-loop experiment

## Key Documents

- `docs/00-project-log.md`
- `docs/01-technical-investigation-report.md`
- `docs/02-minimal-experiment-protocol-draft.md`
- `docs/03-dual-track-and-evaluation-metrics.md`

## Core Architecture Intent

Independent **Control Plane** that owns:
- Goals & milestones
- Task queue
- State & memory
- Budget & resource limits
- Hard permission / policy enforcement
- Human approval gates

AI Manager proposes; Control Plane + Independent Verifier decide and enforce.
