#!/usr/bin/env python3
"""Product Worker entry: derive a job list, execute it, write deliverables.

  PYTHONPATH=. python scripts/worker_run_task.py \\
      --card fixtures/local_support_tickets_demo --out /tmp/tickets-demo-out

The card supplies a goal statement, an input schema, and an input file
(``goal.json`` with ``statement``, ``schema``, and ``input``). Jobs come
from ``TaskDecomposer.decompose()``. The derived list is written to
``derived_dispatch.json`` in the output directory. That file is an output.

This script does not read ``dispatch.json`` and does not import
``worker_jobs.py``. ``--task-id DS-T1-20261108`` and ``--task-id
DS-T2-20261110`` are refused so those observation runs are not repeated.

L2 remains CONDITIONAL. It is not granted and not accepted.
Production 7×24 is NOT ACCEPTED. The L2-2 72h clock is NOT STARTED.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_plane.derived_worker import (  # noqa: E402
    CLAIM_BOUNDARY,
    HISTORICAL_OBSERVATION_TASK_IDS,
    run_card,
    run_goal,
)


_USAGE_ERRORS = {
    "invalid_args",
    "missing_inbox",
    "missing_goal",
    "invalid_goal",
    "missing_input_path",
    "input_escapes_card",
    "refusing_historical_observation_task",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive, execute, and deliver a worker run")
    parser.add_argument("--task-id", help="task_inbox/<id> card that already has goal.json")
    parser.add_argument("--card", help="Directory with goal.json and the input file")
    parser.add_argument("--goal", help="goal.json path, used with --input and --out")
    parser.add_argument("--input", help="Input CSV, used with --goal and --out")
    parser.add_argument("--out", help="Deliverable directory")
    args = parser.parse_args(argv)

    modes = [bool(args.task_id), bool(args.card), bool(args.goal or args.input)]
    if sum(modes) != 1:
        return _emit(_usage("invalid_args"), usage=True)

    if args.task_id:
        if args.task_id in HISTORICAL_OBSERVATION_TASK_IDS:
            return _emit(_usage("refusing_historical_observation_task", task_id=args.task_id), usage=True)
        if Path(args.task_id).name != args.task_id:
            return _emit(_usage("invalid_args"), usage=True)
        card = ROOT / "task_inbox" / args.task_id
        if not card.is_dir():
            return _emit(_usage("missing_inbox", task_id=args.task_id), usage=True)
        out = Path(args.out) if args.out else card / "deliverables"
        result = run_card(card, out)
        return _emit(result, usage=result.get("error") in _USAGE_ERRORS)

    if args.card:
        card = Path(args.card)
        out = Path(args.out) if args.out else card / "deliverables"
        result = run_card(card, out)
        return _emit(result, usage=result.get("error") in _USAGE_ERRORS)

    if not (args.goal and args.input and args.out):
        return _emit(_usage("invalid_args"), usage=True)
    goal_path = Path(args.goal)
    try:
        goal = json.loads(goal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _emit(_usage("invalid_goal", detail=type(exc).__name__), usage=True)
    if not isinstance(goal, dict):
        return _emit(_usage("invalid_goal"), usage=True)
    result = run_goal(goal, Path(args.input), Path(args.out))
    return _emit(result, usage=result.get("error") in _USAGE_ERRORS)


def _usage(code: str, **extra: object) -> dict:
    payload = {
        "ok": False,
        "error": code,
        "network": False,
        "paid": False,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    payload.update(extra)
    return payload


def _emit(result: dict, *, usage: bool) -> int:
    print(json.dumps(result, indent=2))
    if result.get("ok"):
        return 0
    return 2 if usage else 1


if __name__ == "__main__":
    raise SystemExit(main())
