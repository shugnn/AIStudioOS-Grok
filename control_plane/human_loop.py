"""Scaffold: bounded offline demo goal for the human-direct-control CLI.

This is operator-written script logic (script manager / worker / verifier).
It is NOT self-tasking, NOT self-iteration, and NOT an autonomy claim.
Production 7x24 remains NOT ACCEPTED.

Used by `python -m control_plane start|authorize|run` so a human can complete
one zero-cost, offline, pre-seeded goal from USER_GUIDE alone.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .control_plane import ControlPlane, ControlPlaneError
from .emergency_stop import is_stopped, status as stop_status
from .models import Goal, GoalStatus, Task, TaskStatus

SCAFFOLD_NOTICE = (
    "[scaffold] Script manager/worker/verifier. "
    "Not self-tasking, not self-iteration, not production 7x24."
)

DEMO_TITLE = "Offline bounded demo (word-count + checksum)"
DEMO_DESCRIPTION = (
    "Zero-cost, offline, pre-seeded demo. A human starts, authorizes, "
    "runs, inspects status, and can emergency-stop from the Control Plane CLI. "
    "Worker and verifier are hard-coded scripts, not an autonomous loop."
)
DEMO_CRITERIA = [
    "both seeded tasks are accepted",
    "artifacts written under artifacts/human_loop/",
    "spent_usd is 0",
]
DEMO_SPECS = (
    ("word_count", {"text": "human direct control minimal loop"}, "hdc-wc1"),
    ("checksum", {"n": 15}, "hdc-cs1"),
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts" / "human_loop"


class EmergencyStopped(RuntimeError):
    """Raised when a run is refused or halted by the emergency-stop file."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def script_worker(kind: str, payload: dict) -> dict:
    if kind == "word_count":
        words = [w for w in payload.get("text", "").split() if w]
        return {"word_count": len(words)}
    if kind == "checksum":
        n = int(payload.get("n", 0))
        return {"n": n, "sum_0_to_n": n * (n + 1) // 2}
    return {"error": f"unknown_kind:{kind}"}


def script_verifier(kind: str, payload: dict, result: dict) -> dict:
    if kind == "word_count":
        expected = len([w for w in str(payload.get("text", "")).split() if w])
        ok = result.get("word_count") == expected
        return {"ok": ok, "expected": expected, "got": result.get("word_count")}
    if kind == "checksum":
        n = int(payload.get("n", 0))
        expected = n * (n + 1) // 2
        ok = result.get("sum_0_to_n") == expected
        return {"ok": ok, "expected": expected, "got": result.get("sum_0_to_n")}
    return {"ok": False, "error": f"unknown_kind:{kind}"}


def start_demo_goal(cp: ControlPlane, title: str | None = None) -> dict:
    """Create the bounded demo goal and propose (not approve) its tasks."""
    if is_stopped():
        raise EmergencyStopped("emergency stop is armed; start is refused")
    goal = cp.create_goal(
        title=title or DEMO_TITLE,
        description=DEMO_DESCRIPTION,
        acceptance_criteria=list(DEMO_CRITERIA),
        budget_usd=1.0,  # unused envelope; demo spend stays $0 (avoids 0/0 hard_stop)
        scaffold=True,
        demo="human_direct_control",
    )
    tasks: list[Task] = []
    for kind, payload, key in DEMO_SPECS:
        task = cp.propose_task(
            goal.id,
            title=f"{kind}:{key}",
            description=json.dumps({"kind": kind, "payload": payload}, sort_keys=True),
            proposed_by="script_manager_scaffold",
            estimated_cost_usd=0.0,
            idempotency_key=key,
            kind=kind,
            payload=payload,
            scaffold=True,
        )
        tasks.append(task)
    return {
        "scaffold": True,
        "notice": SCAFFOLD_NOTICE,
        "goal_id": goal.id,
        "title": goal.title,
        "tasks": [{"id": t.id, "title": t.title, "status": t.status.value} for t in tasks],
    }


def authorize_proposed(cp: ControlPlane, task_id: str | None = None, approver: str = "founder") -> dict:
    """Human authorization: approve one PROPOSED task, or all of them."""
    if task_id:
        pending = [cp._require_task(task_id)]
        if pending[0].status != TaskStatus.PROPOSED:
            raise ControlPlaneError(
                f"Cannot authorize task in status {pending[0].status.value}; expected proposed"
            )
    else:
        pending = [
            t
            for g in cp.store.list_goals()
            for t in cp.list_tasks(g.id, status=TaskStatus.PROPOSED)
        ]
    approved = []
    blocked = []
    for task in pending:
        try:
            t = cp.approve_task(task.id)
            t.unblock_approver = approver
            t.updated_at = _now()
            cp.store.save_task(t)
            approved.append({"id": t.id, "title": t.title, "status": t.status.value})
        except ControlPlaneError as exc:
            blocked.append({"id": task.id, "title": task.title, "error": str(exc)})
    return {
        "approver": approver,
        "approved": approved,
        "blocked": blocked,
        "nothing_to_authorize": not pending,
    }


def _write_artifact(task: Task, kind: str, payload: dict, result: dict) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"{task.id}.json"
    path.write_text(
        json.dumps(
            {
                "scaffold": True,
                "task_id": task.id,
                "kind": kind,
                "payload": payload,
                "result": result,
                "utc": _now(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _process_one(cp: ControlPlane, task: Task) -> dict:
    kind = task.metadata.get("kind") or "word_count"
    payload = task.metadata.get("payload") or {}
    cp.mark_running(task.id)
    result = script_worker(kind, payload)
    art = _write_artifact(task, kind, payload, result)
    rel = art.relative_to(ROOT).as_posix() if art.is_relative_to(ROOT) else str(art)
    cp.check_permission("file_write", path="./" + rel if not rel.startswith(".") else rel)
    cp.submit_for_verification(task.id, str(art))
    verdict = script_verifier(kind, payload, result)
    if verdict.get("ok"):
        done = cp.accept_task(task.id, feedback=json.dumps(verdict, sort_keys=True), cost_usd=0.0)
        status = done.status.value
    else:
        done = cp.reject_task(task.id, feedback=json.dumps(verdict, sort_keys=True))
        status = done.status.value
    return {
        "task_id": task.id,
        "title": task.title,
        "kind": kind,
        "status": status,
        "verify": verdict,
        "artifact": str(art),
    }


def _maybe_complete(cp: ControlPlane, goal: Goal) -> bool:
    tasks = cp.list_tasks(goal.id)
    if not tasks:
        return False
    if all(t.status == TaskStatus.ACCEPTED for t in tasks):
        budget = cp.get_budget()
        if budget.spent_usd != 0:
            return False
        cp.complete_goal(goal.id)
        return True
    return False


def _active_goals(cp: ControlPlane, goal_id: str | None) -> list[Goal]:
    if goal_id:
        goal = cp.get_goal(goal_id)
        if not goal:
            raise ControlPlaneError(f"Goal not found: {goal_id}")
        return [goal]
    goals = [g for g in cp.store.list_goals() if g.status == GoalStatus.ACTIVE]
    if not goals:
        # fall back to most recently updated goal so status-after-complete still works
        all_goals = sorted(cp.store.list_goals(), key=lambda g: g.updated_at, reverse=True)
        return all_goals[:1] if all_goals else []
    return goals


def run_cycle(
    cp: ControlPlane,
    goal_id: str | None = None,
    once: bool = False,
    max_steps: int = 20,
) -> dict:
    """Execute approved tasks with the script worker/verifier. Does not auto-approve."""
    if is_stopped():
        raise EmergencyStopped("emergency stop is armed; run is refused")

    log: list[dict] = []
    halted = False
    completed: list[str] = []
    needs_authorize = 0
    processed_goals: list[str] = []

    for goal in _active_goals(cp, goal_id):
        processed_goals.append(goal.id)
        cp.recover_stale_tasks(goal.id)
        needs_authorize += len(cp.list_tasks(goal.id, status=TaskStatus.PROPOSED))
        while True:
            if is_stopped():
                halted = True
                break
            approved = cp.list_tasks(goal.id, status=TaskStatus.APPROVED)
            if not approved:
                break
            log.append(_process_one(cp, approved[0]))
            if once or len(log) >= max_steps:
                break
        if _maybe_complete(cp, goal):
            completed.append(goal.id)
        if halted or once or len(log) >= max_steps:
            break

    if halted and not log:
        raise EmergencyStopped("emergency stop is armed; run is refused")

    return {
        "scaffold": True,
        "notice": SCAFFOLD_NOTICE,
        "emergency_stop": stop_status() if halted else {"emergency_stop": False},
        "halted": halted,
        "goal_ids": processed_goals,
        "completed_goal_ids": completed,
        "steps": len(log),
        "needs_authorize": needs_authorize,
        "log": log,
    }
