# Minimal Experiment Protocol (Draft)

**Goal**: Prove that a single Manager + single Worker can run a closed Observe-Plan-Execute-Verify-Decide loop with recovery and hard governance, before adding complexity.

## Success Criteria (must pass all)

1. **Task Generation**: Given a high-level goal and current project state, the system autonomously proposes the next concrete, verifiable task.
2. **Execute + Verify**: Worker produces an artifact; independent Verifier accepts or rejects it with structured feedback. Rejection triggers re-planning.
3. **Recovery**: Force-kill the process mid-execution; on restart the system resumes from last consistent checkpoint without losing accepted work.
4. **Governance**: When budget is exhausted or a critical action (e.g. external publish, delete, large spend) is requested, the system **hard-stops** and waits for human approval. Soft prompt-based refusal is not enough.

## Scope Limits (intentionally small)

- One Manager role
- One Worker role (coding preferred)
- One project / one goal
- Maximum 48–72 hours of continuous operation for the first run
- Budget hard limit (e.g. $20–50 token spend)
- No dynamic team hiring yet
- No multi-project yet

## Metrics to Record

| Metric                        | Definition                                      |
|-------------------------------|-------------------------------------------------|
| Effective Task Completion Rate| Accepted tasks / total attempted tasks          |
| Human Interventions / 24h     | Times human had to step in                      |
| Cost per Accepted Task        | Total spend / number of accepted tasks          |
| Invalid Loop Rate             | Cycles that produced no measurable progress     |
| Recovery Success Rate         | Successful resumes after forced crash           |
| Permission Violation Attempts | Times system tried to exceed hard rules         |
| Actual Deliverable            | Is there a testable, usable outcome?            |

## Candidate Experiment Target

Prefer a small, self-contained task that can be validated automatically (unit tests + simple acceptance criteria).  
Possible sources: simplified slice of LCS-Watcher / LCS-opt, or a synthetic “build a tiny CLI tool with tests” goal.

## Implementation Notes

- Control Plane owns: Goal, Task Queue, Budget Counter, Permission Policy, Checkpoint Store.
- Manager only proposes; Control Plane + Verifier decide acceptance and resource release.
- Worker is sandboxed (OpenHands preferred first).

This protocol will be refined after the investigation report is reviewed.
