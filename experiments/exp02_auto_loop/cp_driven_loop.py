#!/usr/bin/env python3
"""Exp-02b: Control Plane–driven continuous execution loop ($0, no LLM).

Wire:
  Manager proposes tasks (idempotent keys)
  Control Plane approves / reserves budget / hard-stops
  Worker executes deterministic jobs
  Independent Verifier recomputes expected results
  Control Plane accept | reject
  Loop until no APPROVED/PROPOSED work or max_steps

Can be invoked once per L1 wake: --once
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from control_plane.control_plane import ControlPlane, ControlPlaneError
from control_plane.models import TaskStatus
from control_plane.store import FileStore

OUT = ROOT / "docs" / "progress" / "exp02_auto_loop"
OUT.mkdir(parents=True, exist_ok=True)
STATE = Path("/tmp/aistudio_exp02b/cp_state.json")


def worker(kind: str, payload: dict) -> dict:
    if kind == "word_count":
        words = [w for w in payload.get("text", "").split() if w]
        return {"word_count": len(words)}
    if kind == "checksum":
        n = int(payload.get("n", 0))
        return {"n": n, "sum_0_to_n": n * (n + 1) // 2}
    return {"error": f"unknown_kind:{kind}"}


def verifier(kind: str, payload: dict, result: dict) -> dict:
    if kind == "word_count":
        expected = len([w for w in payload.get("text", "").split() if w])
        ok = result.get("word_count") == expected
        return {"ok": ok, "expected": expected, "got": result.get("word_count")}
    if kind == "checksum":
        n = int(payload.get("n", 0))
        expected = n * (n + 1) // 2
        ok = result.get("sum_0_to_n") == expected
        return {"ok": ok, "expected": expected, "got": result.get("sum_0_to_n")}
    return {"ok": False, "error": "unknown_kind"}


def seed_if_empty(cp: ControlPlane, goal_id: str) -> None:
    existing = cp.list_tasks(goal_id)
    if existing:
        return
    specs = [
        ("word_count", {"text": "control plane driven closed loop"}, "exp02b-wc1"),
        ("checksum", {"n": 50}, "exp02b-cs1"),
        ("word_count", {"text": "wake execute verify next"}, "exp02b-wc2"),
        ("checksum", {"n": 20}, "exp02b-cs2"),
    ]
    for kind, payload, key in specs:
        t = cp.propose_task(
            goal_id,
            title=f"{kind}:{key}",
            description=json.dumps({"kind": kind, "payload": payload}),
            proposed_by="script_manager",
            estimated_cost_usd=0.0,
            idempotency_key=key,
            kind=kind,
            payload=payload,
        )
        cp.approve_task(t.id)


def process_one(cp: ControlPlane, goal_id: str) -> dict | None:
    approved = cp.list_tasks(goal_id, status=TaskStatus.APPROVED)
    if not approved:
        # try promote any PROPOSED with zero cost
        for t in cp.list_tasks(goal_id, status=TaskStatus.PROPOSED):
            try:
                cp.approve_task(t.id)
            except ControlPlaneError:
                continue
        approved = cp.list_tasks(goal_id, status=TaskStatus.APPROVED)
    if not approved:
        return None

    task = approved[0]
    kind = task.metadata.get("kind") or "word_count"
    payload = task.metadata.get("payload") or {}
    if not payload and task.description.startswith("{"):
        try:
            d = json.loads(task.description)
            kind = d.get("kind", kind)
            payload = d.get("payload", payload)
        except json.JSONDecodeError:
            pass

    cp.mark_running(task.id)
    result = worker(kind, payload)
    art = OUT / f"artifact-{task.id}.json"
    art.write_text(json.dumps({"result": result, "kind": kind, "payload": payload}, indent=2))
    cp.submit_for_verification(task.id, str(art))

    v = verifier(kind, payload, result)
    if v.get("ok"):
        cp.accept_task(task.id, feedback=json.dumps(v), cost_usd=0.0, cost_tokens=0)
        status = "accepted"
    else:
        cp.reject_task(task.id, feedback=json.dumps(v))
        status = "rejected"

    return {
        "task_id": task.id,
        "kind": kind,
        "status": status,
        "verify": v,
        "artifact": str(art),
    }


def ensure_goal(cp: ControlPlane) -> str:
    # reuse goal id from state metadata file if present
    meta_path = Path("/tmp/aistudio_exp02b/goal_id.txt")
    if meta_path.exists():
        gid = meta_path.read_text().strip()
        if cp.get_goal(gid):
            return gid
    g = cp.create_goal(
        title="Exp-02b CP-driven auto loop",
        description="Continuous script Manager→Worker→Verifier under Control Plane",
        acceptance_criteria=["all seeded tasks accepted", "zero human mid-loop", "$0 spend"],
        budget_usd=1.0,
    )
    meta_path.write_text(g.id)
    return g.id


def run(max_steps: int = 10, once: bool = False) -> dict:
    store = FileStore(STATE)
    cp = ControlPlane(store)
    goal_id = ensure_goal(cp)
    seed_if_empty(cp, goal_id)

    log = []
    steps = 0
    limit = 1 if once else max_steps
    while steps < limit:
        item = process_one(cp, goal_id)
        if item is None:
            break
        log.append(item)
        steps += 1

    tasks = [t.to_dict() for t in cp.list_tasks(goal_id)]
    budget = cp.get_budget().to_dict()
    report = {
        "experiment": "exp02b_cp_driven_loop",
        "utc": datetime.now(timezone.utc).isoformat(),
        "goal_id": goal_id,
        "steps_this_wake": steps,
        "once": once,
        "accepted": sum(1 for t in tasks if t["status"] == "accepted"),
        "rejected": sum(1 for t in tasks if t["status"] == "rejected"),
        "approved_left": sum(1 for t in tasks if t["status"] == "approved"),
        "human_interventions": 0,
        "budget": budget,
        "llm_used": False,
        "log": log,
    }
    path = OUT / f"exp02b-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact"] = str(path)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="process at most one task (L1 wake)")
    ap.add_argument("--max-steps", type=int, default=10)
    ap.add_argument("--reset", action="store_true", help="wipe exp state and reseed")
    args = ap.parse_args()
    if args.reset:
        for p in [STATE, STATE.with_suffix(".bak"), Path("/tmp/aistudio_exp02b/goal_id.txt")]:
            if p.exists():
                p.unlink()
        for p in OUT.glob("artifact-*.json"):
            p.unlink()
    r = run(max_steps=args.max_steps, once=args.once)
    print(json.dumps({k: r[k] for k in r if k != "log"}, indent=2))
    # success if this wake did work or queue already drained with accepts
    if r["rejected"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
