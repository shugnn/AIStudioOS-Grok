# Exp-01: Tiny Word-Count CLI

**Protocol**: see `docs/04-minimal-experiment-protocol-v1.md`

## Goal

Build a pure-Python CLI `wcmini` that reports lines, words, and bytes for given files, with unit tests.

## Layout

```
experiments/exp01-tiny-cli/
├── README.md
├── workspace/          # Worker writes code here
│   └── (wcmini package will appear here)
├── fixtures/           # Test input files
└── results.md          # Metrics & outcome after the run
```

## How the Control Plane is used

```python
from control_plane import ControlPlane

cp = ControlPlane()
goal = cp.create_goal(
    title="Build a tiny word-count CLI",
    description="...",
    acceptance_criteria=[...],
    budget_usd=5.0,
)
task = cp.propose_task(goal.id, "Scaffold package", "...")
cp.approve_task(task.id)
# ... Worker runs ...
# ... Verifier accepts or rejects ...
```

## Human CLI

```bash
python -m control_plane.cli status
python -m control_plane.cli raise-budget 5.0
python -m control_plane.cli approve <task_id>
```
