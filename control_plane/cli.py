#!/usr/bin/env python3
"""Simple CLI to inspect and operate the Control Plane (human interface)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_plane import ControlPlane, TaskStatus


def main():
    parser = argparse.ArgumentParser(description="AIStudioOS Control Plane CLI")
    parser.add_argument("--state", default="control_plane/state.json", help="State file path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # status
    sub.add_parser("status", help="Show budget, goals, recent tasks")

    # raise-budget
    p_budget = sub.add_parser("raise-budget", help="Human raises budget ceiling")
    p_budget.add_argument("amount", type=float, help="Additional USD")

    # approve
    p_approve = sub.add_parser("approve", help="Approve a proposed/rejected task")
    p_approve.add_argument("task_id")

    # list-tasks
    p_list = sub.add_parser("list-tasks", help="List tasks for a goal")
    p_list.add_argument("goal_id")
    p_list.add_argument("--status", default=None)

    # policy
    p_policy = sub.add_parser("policy", help="Show or update permission policy")
    p_policy.add_argument("--allow-network", type=lambda x: x.lower() == "true", default=None)
    p_policy.add_argument("--allow-git-push", type=lambda x: x.lower() == "true", default=None)

    args = parser.parse_args()
    cp = ControlPlane(store=__import__("control_plane.store", fromlist=["FileStore"]).FileStore(args.state))

    if args.cmd == "status":
        budget = cp.get_budget()
        goals = cp.store.list_goals()
        print("=== Budget ===")
        print(f"  Total: ${budget.total_usd:.2f}  Spent: ${budget.spent_usd:.2f}  "
              f"Remaining: ${budget.remaining_usd():.2f}  Hard-stop: {budget.hard_stop}")
        print("\n=== Goals ===")
        for g in goals:
            print(f"  [{g.status.value}] {g.id}  {g.title}")
            tasks = cp.list_tasks(g.id)
            for t in tasks:
                print(f"      [{t.status.value}] {t.id}  {t.title}")
        print("\n=== Policy ===")
        print(json.dumps(cp.store.get_policy().to_dict(), indent=2))

    elif args.cmd == "raise-budget":
        b = cp.raise_budget(args.amount)
        print(f"Budget raised. New total: ${b.total_usd:.2f}, hard_stop={b.hard_stop}")

    elif args.cmd == "approve":
        try:
            t = cp.approve_task(args.task_id)
            print(f"Approved: {t.id} -> {t.status.value}")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

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


if __name__ == "__main__":
    main()
