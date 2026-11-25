#!/usr/bin/env python3
"""Human interface to the Control Plane.

Entrypoint: `python -m control_plane <command>` (also `python control_plane/cli.py`).

This CLI is the host-side path for start, authorize, status, run, and
emergency-stop. Scripted demo work behind `start`/`run` is scaffold, not autonomy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_plane import ControlPlane, ControlPlaneError, TaskStatus
from control_plane.emergency_stop import arm, clear, status as stop_status
from control_plane.human_loop import (
    SCAFFOLD_NOTICE,
    EmergencyStopped,
    authorize_proposed,
    run_cycle,
    start_demo_goal,
)
from control_plane.store import FileStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_STOP = 3


def _cp(state: str) -> ControlPlane:
    return ControlPlane(store=FileStore(state))


def _print_status(cp: ControlPlane) -> None:
    budget = cp.get_budget()
    goals = cp.store.list_goals()
    stop = stop_status()
    print("=== Emergency stop ===")
    print(f"  Armed: {stop['emergency_stop']}")
    print(f"  Path: {stop['path']}")
    if stop["emergency_stop"]:
        print(f"  Reason: {stop['reason']}")
    print("\n=== Budget ===")
    print(
        f"  Total: ${budget.total_usd:.2f}  Spent: ${budget.spent_usd:.2f}  "
        f"Reserved: ${budget.reserved_usd:.2f}  "
        f"Remaining: ${budget.remaining_usd():.2f}  Hard-stop: {budget.hard_stop}"
    )
    print("\n=== Goals ===")
    if not goals:
        print("  (none)")
    for g in goals:
        print(f"  [{g.status.value}] {g.id}  {g.title}")
        tasks = cp.list_tasks(g.id)
        for t in tasks:
            extra = f"  blocked={t.block_reason}" if t.block_reason else ""
            print(f"      [{t.status.value}] {t.id}  {t.title}{extra}")
    print("\n=== Policy ===")
    print(json.dumps(cp.store.get_policy().to_dict(), indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="AIStudioOS Control Plane CLI (human direct control)"
    )
    parser.add_argument("--state", default="control_plane/state.json", help="State file path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser(
        "start",
        help="Create the bounded offline demo goal and propose its tasks (not approved)",
    )
    p_start.add_argument("--title", default=None, help="Optional goal title override")

    sub.add_parser("status", help="Show emergency-stop flag, budget, goals, tasks, policy")

    p_auth = sub.add_parser(
        "authorize",
        help="Human authorization: approve all PROPOSED tasks, or one task id",
    )
    p_auth.add_argument("task_id", nargs="?", default=None)
    p_auth.add_argument("--approver", default="founder")

    p_budget = sub.add_parser("raise-budget", help="Human raises budget ceiling")
    p_budget.add_argument("amount", type=float, help="Additional USD")

    p_approve = sub.add_parser("approve", help="Approve a single proposed/rejected task")
    p_approve.add_argument("task_id")

    p_unblock = sub.add_parser("unblock", help="Human unblocks a BLOCKED task")
    p_unblock.add_argument("task_id")
    p_unblock.add_argument("--approver", default="founder")

    p_list = sub.add_parser("list-tasks", help="List tasks for a goal")
    p_list.add_argument("goal_id")
    p_list.add_argument("--status", default=None)

    p_policy = sub.add_parser("policy", help="Show or update permission policy")
    p_policy.add_argument("--allow-network", type=lambda x: x.lower() == "true", default=None)
    p_policy.add_argument("--allow-git-push", type=lambda x: x.lower() == "true", default=None)

    p_run = sub.add_parser(
        "run",
        help="Run approved tasks with the scripted demo worker (scaffold; does not auto-approve)",
    )
    p_run.add_argument("--goal", dest="goal_id", default=None, help="Goal id (default: active goals)")
    p_run.add_argument("--once", action="store_true", help="Process at most one approved task")
    p_run.add_argument("--max-steps", type=int, default=20)

    p_stop = sub.add_parser(
        "emergency-stop",
        help="Arm the emergency-stop file so run/start refuse new work",
    )
    p_stop.add_argument("--reason", default="stop", help="Reason written into the stop file")

    sub.add_parser("clear-stop", help="Clear the emergency-stop file")

    args = parser.parse_args(argv)
    cp = _cp(args.state)

    if args.cmd == "start":
        try:
            result = start_demo_goal(cp, title=args.title)
        except EmergencyStopped as e:
            print(f"Error: {e}", file=sys.stderr)
            print(json.dumps(stop_status(), indent=2), file=sys.stderr)
            sys.exit(EXIT_STOP)
        print(SCAFFOLD_NOTICE)
        print(json.dumps(result, indent=2))
        print("Next: python -m control_plane status")
        print("Then authorize: python -m control_plane authorize")

    elif args.cmd == "status":
        _print_status(cp)

    elif args.cmd == "authorize":
        try:
            result = authorize_proposed(cp, task_id=args.task_id, approver=args.approver)
        except (ControlPlaneError, Exception) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(EXIT_ERROR)
        print(json.dumps(result, indent=2))
        if result["nothing_to_authorize"]:
            print("No PROPOSED tasks to authorize.")
        elif result["approved"]:
            print("Next: python -m control_plane run")

    elif args.cmd == "raise-budget":
        b = cp.raise_budget(args.amount)
        print(f"Budget raised. New total: ${b.total_usd:.2f}, hard_stop={b.hard_stop}")

    elif args.cmd == "approve":
        try:
            t = cp.approve_task(args.task_id)
            print(f"Approved: {t.id} -> {t.status.value}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(EXIT_ERROR)

    elif args.cmd == "unblock":
        try:
            t = cp.unblock_task(args.task_id, approver=args.approver)
            print(f"Unblocked by {args.approver}: {t.id} -> {t.status.value}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(EXIT_ERROR)

    elif args.cmd == "list-tasks":
        status = TaskStatus(args.status) if args.status else None
        tasks = cp.list_tasks(args.goal_id, status=status)
        for t in tasks:
            print(f"[{t.status.value}] {t.id}  {t.title}")

    elif args.cmd == "policy":
        kwargs = {}
        if args.allow_network is not None:
            kwargs["allow_network"] = args.allow_network
        if args.allow_git_push is not None:
            kwargs["allow_git_push"] = args.allow_git_push
        if kwargs:
            p = cp.update_policy(**kwargs)
            print("Updated policy:")
        else:
            p = cp.store.get_policy()
        print(json.dumps(p.to_dict(), indent=2))

    elif args.cmd == "run":
        try:
            result = run_cycle(
                cp, goal_id=args.goal_id, once=args.once, max_steps=args.max_steps
            )
        except EmergencyStopped as e:
            print(f"Error: {e}", file=sys.stderr)
            print(json.dumps(stop_status(), indent=2), file=sys.stderr)
            sys.exit(EXIT_STOP)
        except ControlPlaneError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(EXIT_ERROR)
        print(json.dumps(result, indent=2))
        if result["halted"]:
            sys.exit(EXIT_STOP)
        if result["needs_authorize"] and result["steps"] == 0:
            print("No approved work. Authorize proposed tasks first: python -m control_plane authorize")
        if result["completed_goal_ids"]:
            print("Goal completed:", ", ".join(result["completed_goal_ids"]))

    elif args.cmd == "emergency-stop":
        path = arm(args.reason)
        print(json.dumps({"armed": True, "path": str(path), "reason": args.reason}, indent=2))

    elif args.cmd == "clear-stop":
        removed = clear()
        print(json.dumps({"cleared": removed, **stop_status()}, indent=2))


if __name__ == "__main__":
    main()
