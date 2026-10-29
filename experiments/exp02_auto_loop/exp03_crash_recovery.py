#!/usr/bin/env python3
"""Exp-03: crash mid-RUNNING then recover on next wake (FOUNDER-20261024-AUTOLOOP)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "progress" / "exp03_crash_recovery"
OUT.mkdir(parents=True, exist_ok=True)

from control_plane.control_plane import ControlPlane
from control_plane.models import TaskStatus
from control_plane.store import FileStore
from experiments.exp02_auto_loop.cp_driven_loop import (
    STATE,
    ensure_goal,
    seed_if_empty,
    run,
    wipe_exp_state,
    worker,
)


def main() -> int:
    log = []
    wipe_exp_state()
    store = FileStore(STATE)
    cp = ControlPlane(store)
    goal_id = ensure_goal(cp)
    seed_if_empty(cp, goal_id)
    approved = cp.list_tasks(goal_id, status=TaskStatus.APPROVED)
    assert approved, "need approved tasks"
    victim = approved[0]
    cp.mark_running(victim.id)
    log.append(
        {
            "phase": "crash_injected",
            "task_id": victim.id,
            "status": "running",
            "utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    r1 = run(max_steps=10, once=False)
    log.append({"phase": "after_recovery_drain", "report": {k: r1[k] for k in r1 if k != "log"}})

    wipe_exp_state()
    store = FileStore(STATE)
    cp = ControlPlane(store)
    goal_id = ensure_goal(cp)
    seed_if_empty(cp, goal_id)
    t = cp.list_tasks(goal_id, status=TaskStatus.APPROVED)[0]
    cp.mark_running(t.id)
    kind = t.metadata.get("kind", "word_count")
    payload = t.metadata.get("payload", {})
    result = worker(kind, payload)
    art = ROOT / "docs/progress/exp02_auto_loop" / f"artifact-{t.id}.json"
    art.write_text(json.dumps({"result": result, "kind": kind, "payload": payload}, indent=2))
    cp.submit_for_verification(t.id, str(art))
    log.append({"phase": "crash_in_verifying", "task_id": t.id, "artifact": str(art)})
    r2 = run(max_steps=10, once=False)
    log.append({"phase": "after_verifying_recovery", "report": {k: r2[k] for k in r2 if k != "log"}})

    ok = r1.get("accepted", 0) >= 4 and r2.get("accepted", 0) >= 4 and r1.get("rejected", 0) == 0
    evidence = {
        "experiment": "exp03_crash_recovery",
        "utc": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "human_interventions": 0,
        "budget_usd": 0,
        "state_path": str(STATE),
        "log": log,
    }
    path = OUT / f"exp03-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": ok,
                "artifact": str(path),
                "r1_accepted": r1.get("accepted"),
                "r2_accepted": r2.get("accepted"),
            },
            indent=2,
        )
    )
    (OUT / "README.md").write_text(
        "# Exp-03 crash recovery\n\n"
        "1. mark_running then simulate process death → recover_stale_tasks → APPROVED → drain\n"
        "2. leave VERIFYING with artifact → finish_verifying on next wake\n\n"
        f"Latest: `{path.name}` ok={ok}\n"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
