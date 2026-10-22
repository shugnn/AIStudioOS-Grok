# Dual-Track Parallel Development & Unified Evaluation Metrics

**Date**: 2026-10-22  
**Status**: Aligned with ChatGPT track

## 1. Project Relationship

| Project                | Lead     | Positioning                          | Suggested GitHub Repo              |
|------------------------|----------|--------------------------------------|-----------------------------------|
| AIStudioOS-ChatGPT     | ChatGPT  | Independent R&D and implementation   | shugnn/AIStudioOS-ChatGPT         |
| AIStudioOS-Grok        | Grok     | Independent R&D and implementation   | shugnn/AIStudioOS-Grok            |

### Operating Principles (Agreed)

1. **Independent R&D**: Each track performs its own technology selection, architecture design, development, and testing. No forced convergence on the same tech stack.
2. **Independent repositories**: Code, tasks, docs, and experiment data are managed separately to avoid interference.
3. **Unified goal**: Both aim to build a long-running, autonomous AI Studio OS with a human founder as final decision-maker.
4. **Objective comparison**: Use the same acceptance metrics to compare autonomy, reliability, cost, and real delivery quality.
5. **Later complementarity**: Proven effective components from either side can be integrated in the future.

## 2. Unified Evaluation Metrics (for fair comparison)

These metrics will be measured under comparable conditions (same or equivalent experimental tasks, similar budget envelopes, same observation windows).

| Metric                        | Description                                                                 | How to measure                                      | Target for Phase 1 Minimal Experiment |
|-------------------------------|-----------------------------------------------------------------------------|-----------------------------------------------------|---------------------------------------|
| Autonomous Task Completion Rate | Percentage of proposed tasks that pass independent verification and are accepted | Accepted tasks / Total attempted tasks             | ≥ 60%                                 |
| Continuous Effective Runtime  | Wall-clock time of continuous forward progress without human intervention   | Hours of unattended effective work                  | ≥ 24–72 hours (stretch)               |
| Human Interventions per 24h   | Number of times a human must step in to unblock or correct                  | Count of required human actions                     | ≤ 2–3                                 |
| Fault Recovery Capability     | Ability to resume correctly after forced process kill / crash               | Successful resumes / Forced crash attempts          | 100% on tested crashes                |
| Cost per Accepted Task        | Total token + compute spend divided by number of accepted tasks             | $ spent / Accepted tasks                            | Track & minimize                      |
| Permission & Safety Control   | Number of times the system attempts actions beyond hard policy limits       | Unauthorized action attempts (should be blocked)    | 0 successful violations               |
| Actual Deliverable Quality    | Whether a testable, usable artifact is produced                             | Binary + qualitative review                         | Yes (functional outcome)              |

**Important**: Continuous runtime alone is **not** the primary success criterion. Effective delivery + low intervention + recovery + governance compliance are higher priority.

## 3. AIStudioOS-Grok Current Status Alignment

- Local project already initialized under `/home/workdir/artifacts/AIStudioOS-Grok`
- Technical Investigation Report v0.1 completed
- Minimal Experiment Protocol draft written
- Ready to proceed with independent experiment design and thin Control Plane prototyping
- Will not share intermediate code or force technology choices with the ChatGPT track

## 4. Recommended Next Steps for Repository Setup

User (shugnn) should create the two GitHub repositories:

1. `shugnn/AIStudioOS-ChatGPT`
2. `shugnn/AIStudioOS-Grok`

Once `shugnn/AIStudioOS-Grok` exists, this local work can be pushed as the initial content (README + docs + investigation report).

Until the remote repo is created by the user, all work continues in the local sandbox under AIStudioOS-Grok.
