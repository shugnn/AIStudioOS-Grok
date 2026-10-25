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
    if kind == "fail_once":
        # Worker may "succeed" with wrong result; Verifier must catch it
        return {"word_count": -1, "injected": True}
    if kind == "fail_always":
        return {"word_count": -1, "injected": True, "always": True}
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
    if kind == "fail_once":
        expected = len([w for w in payload.get("text", "x").split() if w])
        ok = result.get("word_count") == expected
        return {"ok": ok, "expected": expected, "got": result.get("word_count"), "injected": True}
    if kind == "fail_always":
        expected = len([w for w in payload.get("text", "x").split() if w])
        ok = result.get("word_count") == expected
        return {"ok": ok, "expected": expected, "got": result.get("word_count"), "always_fail": True}
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
    # optional long queue via env EXP02_STRESS=1
    import os
    if os.environ.get("EXP02_STRESS") == "1":
        for i in range(6):
            specs.append(("checksum", {"n": 5 + i}, f"exp02b-stress-{i}"))
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


def finish_verifying(cp: ControlPlane, goal_id: str) -> dict | None:
    """Complete VERIFYING tasks that already have artifacts (post-crash)."""
    for task in cp.list_tasks(goal_id, status=TaskStatus.VERIFYING):
        kind = task.metadata.get("kind") or "word_count"
        payload = task.metadata.get("payload") or {}
        result = {}
        if task.artifact_path and Path(task.artifact_path).exists():
            try:
                result = json.loads(Path(task.artifact_path).read_text()).get("result", {})
                kind = json.loads(Path(task.artifact_path).read_text()).get("kind", kind)
                payload = json.loads(Path(task.artifact_path).read_text()).get("payload", payload)
            except Exception:
                pass
        if not result:
            # cannot verify without artifact — return to APPROVED for re-run
            task.status = TaskStatus.APPROVED
            task.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            cp.store.save_task(task)
            continue
        v = verifier(kind, payload, result)
        if v.get("ok"):
            cp.accept_task(task.id, feedback=json.dumps(v), cost_usd=0.0, cost_tokens=0)
            return {"task_id": task.id, "kind": kind, "status": "accepted", "verify": v, "recovered": True}
        cp.reject_task(task.id, feedback=json.dumps(v))
        return {"task_id": task.id, "kind": kind, "status": "rejected", "verify": v, "recovered": True}
    return None


def process_one(cp: ControlPlane, goal_id: str) -> dict | None:
    recovered = cp.recover_stale_tasks(goal_id)
    fin = finish_verifying(cp, goal_id)
    if fin is not None:
        return fin
    # Re-queue REJECTED tasks that still have retry budget (same task_id → CANCELLED path)
    for t in cp.list_tasks(goal_id, status=TaskStatus.REJECTED):
        if t.retry_count <= t.max_retries:
            try:
                cp.approve_task(t.id)
            except ControlPlaneError:
                pass
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
        retry_action = None
    else:
        cp.reject_task(task.id, feedback=json.dumps(v))
        status = "rejected"
        retry_action = None
        task2 = cp._require_task(task.id)
        if task2.status == TaskStatus.CANCELLED:
            retry_action = {"cancelled": True, "retry_count": task2.retry_count, "max_retries": task2.max_retries}
        elif kind == "fail_always":
            # same task will be re-approved next step until CANCELLED
            retry_action = {"same_task_retry": True, "retry_count": task2.retry_count, "max_retries": task2.max_retries}
        elif task2.status == TaskStatus.REJECTED and task2.retry_count < task2.max_retries:
            # fail_once → convert to honest word_count on new task
            new_kind = "word_count" if kind == "fail_once" else kind
            new_payload = payload if kind != "fail_once" else {"text": payload.get("text", "retry ok")}
            key = f"{task.idempotency_key or task.id}-retry{task2.retry_count}"
            nt = cp.propose_task(
                goal_id,
                title=f"retry:{new_kind}:{key}",
                description=json.dumps({"kind": new_kind, "payload": new_payload}),
                proposed_by="script_manager_retry",
                estimated_cost_usd=0.0,
                idempotency_key=key,
                kind=new_kind,
                payload=new_payload,
            )
            try:
                cp.approve_task(nt.id)
                retry_action = {"new_task_id": nt.id, "key": key}
            except ControlPlaneError as e:
                retry_action = {"error": str(e)}

    return {
        "task_id": task.id,
        "kind": kind,
        "status": status,
        "verify": v,
        "artifact": str(art),
        "retry_action": retry_action,
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


def run(max_steps: int = 10, once: bool = False, inject_fail: bool = False) -> dict:
    store = FileStore(STATE)
    cp = ControlPlane(store)
    goal_id = ensure_goal(cp)
    seed_if_empty(cp, goal_id)
    cp.recover_stale_tasks(goal_id)
    if inject_fail:
        # only if not already present
        keys = {t.idempotency_key for t in cp.list_tasks(goal_id)}
        if 'exp02b-fail1' not in keys:
            ft = cp.propose_task(goal_id, title='fail_once:exp02b-fail1',
                description=json.dumps({'kind':'fail_once','payload':{'text':'should fail first'}}),
                proposed_by='script_manager', estimated_cost_usd=0.0,
                idempotency_key='exp02b-fail1', kind='fail_once',
                payload={'text':'should fail first'})
            cp.approve_task(ft.id)


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
    ap.add_argument("--inject-fail", action="store_true", help="seed a fail_once task for verifier isolation test")
    args = ap.parse_args()
    if args.reset:
        for p in [STATE, STATE.with_suffix(".bak"), Path("/tmp/aistudio_exp02b/goal_id.txt")]:
            if p.exists():
                p.unlink()
        for p in OUT.glob("artifact-*.json"):
            p.unlink()
    r = run(max_steps=args.max_steps, once=args.once, inject_fail=args.inject_fail)
    print(json.dumps({k: r[k] for k in r if k != "log"}, indent=2))
    # inject-fail path expects >=1 reject then recovery accepts
    if args.inject_fail:
        return 0 if r["accepted"] >= 4 else 1
    if r["rejected"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
