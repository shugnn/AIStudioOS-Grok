#!/usr/bin/env python3
"""Exp-04: max_retries → CANCELLED + long queue stress ($0)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from control_plane.control_plane import ControlPlane
from control_plane.models import TaskStatus
from control_plane.store import FileStore
from experiments.exp02_auto_loop.cp_driven_loop import (
    STATE,
    OUT,
    ensure_goal,
    run,
    process_one,
)

EVIDENCE = ROOT / "docs" / "progress" / "exp04_cancel_stress"
EVIDENCE.mkdir(parents=True, exist_ok=True)


def reset_state():
    for p in [STATE, STATE.with_suffix(".bak"), Path("/tmp/aistudio_exp02b/goal_id.txt")]:
        if p.exists():
            p.unlink()
    for p in OUT.glob("artifact-*.json"):
        p.unlink()


def test_cancel_path() -> dict:
    reset_state()
    store = FileStore(STATE)
    cp = ControlPlane(store)
    goal_id = ensure_goal(cp)
    # single always-fail task with max_retries=2 → 3 rejects then CANCELLED
    # reject increments: 1,2,3 and on 3rd when retry_count > max_retries → CANCELLED
    # max_retries=2 means after retry_count becomes 3, cancel. So 3 reject cycles.
    t = cp.propose_task(
        goal_id,
        title="fail_always:cancel-test",
        description=json.dumps({"kind": "fail_always", "payload": {"text": "never ok"}}),
        proposed_by="exp04",
        estimated_cost_usd=0.0,
        idempotency_key="exp04-fail-always",
        max_retries=2,
        kind="fail_always",
        payload={"text": "never ok"},
    )
    cp.approve_task(t.id)
    steps = []
    for i in range(10):
        item = process_one(cp, goal_id)
        if item is None:
            break
        task = cp._require_task(t.id)
        steps.append({
            "i": i,
            "item_status": item.get("status"),
            "task_status": task.status.value,
            "retry_count": task.retry_count,
            "retry_action": item.get("retry_action"),
        })
        if task.status == TaskStatus.CANCELLED:
            break
    final = cp._require_task(t.id)
    return {
        "ok": final.status == TaskStatus.CANCELLED and final.retry_count > final.max_retries,
        "final_status": final.status.value,
        "retry_count": final.retry_count,
        "max_retries": final.max_retries,
        "steps": steps,
    }


def test_long_queue(n: int = 50) -> dict:
    reset_state()
    store = FileStore(STATE)
    cp = ControlPlane(store)
    goal_id = ensure_goal(cp)
    for i in range(n):
        kind = "word_count" if i % 2 == 0 else "checksum"
        payload = {"text": f"stress task number {i}"} if kind == "word_count" else {"n": i + 1}
        key = f"exp04-stress-{i}"
        t = cp.propose_task(
            goal_id,
            title=f"{kind}:{key}",
            description=json.dumps({"kind": kind, "payload": payload}),
            proposed_by="exp04",
            estimated_cost_usd=0.0,
            idempotency_key=key,
            kind=kind,
            payload=payload,
        )
        cp.approve_task(t.id)
    r = run(max_steps=n + 5, once=False)
    tasks = cp.list_tasks(goal_id)
    accepted = sum(1 for t in tasks if t.status == TaskStatus.ACCEPTED)
    return {
        "ok": accepted == n and r.get("rejected", 0) == 0,
        "n": n,
        "accepted": accepted,
        "rejected": r.get("rejected"),
        "steps_this_wake": r.get("steps_this_wake"),
        "artifact": r.get("artifact"),
    }


def main() -> int:
    c = test_cancel_path()
    s = test_long_queue(50)
    report = {
        "experiment": "exp04_cancel_and_stress",
        "utc": datetime.now(timezone.utc).isoformat(),
        "cancel_path": c,
        "long_queue": s,
        "ok": c["ok"] and s["ok"],
        "human_interventions": 0,
        "budget_usd": 0,
        "llm_used": False,
    }
    path = EVIDENCE / f"exp04-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (EVIDENCE / "README.md").write_text(
        "# Exp-04 CANCELLED path + long queue\n\n"
        f"- cancel_path ok={c['ok']} status={c['final_status']} retries={c['retry_count']}/{c['max_retries']}\n"
        f"- long_queue ok={s['ok']} accepted={s['accepted']}/{s['n']}\n"
        f"- evidence: `{path.name}`\n"
    )
    print(json.dumps({"ok": report["ok"], "cancel": c["ok"], "stress": s["ok"],
                      "final_status": c["final_status"], "accepted": s["accepted"],
                      "artifact": str(path)}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
