#!/usr/bin/env python3
"""Product Worker entry — run by task_id.

  PYTHONPATH=. python scripts/worker_run_task.py --task-id DS-T1-20261108
  PYTHONPATH=. python scripts/worker_run_task.py --task-id DS-T4-20261112
  PYTHONPATH=. python scripts/worker_run_task.py --task-id DS-T5-20261112

DS-T4 reject-then-revise mode spawns the Worker and the Verifier as separate
processes. The parent records the result. It does not judge the candidate and
it does not call a model API.

DS-T5 model-involved semantic revision likewise spawns Worker and Verifier as
separate processes. Only the interpret_complaint Worker step may call the
model API, and only when the founder has confirmed a paid run.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_TASK_IDS = frozenset(
    {
        "DS-T1-20261108",
        "DS-T2-20261110",
        "DS-T3-20261111",
    }
)
WORKER_STEPS = ("prepare_input", "verify_input", "interpret_complaint", "revise")


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_jobs(inbox: Path, task_id: str):
    jobs_py = inbox / "worker_jobs.py"
    if not jobs_py.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"worker_jobs_{task_id}", jobs_py)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _emit_worker(step: str, result: dict) -> int:
    payload = dict(result)
    payload["role"] = "worker"
    payload["step"] = step
    payload["pid"] = os.getpid()
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def _run_worker_step(inbox: Path, task_id: str, step: str) -> int:
    mod = _load_jobs(inbox, task_id)
    if mod is None:
        return _emit_worker(step, {"ok": False, "error": "worker_jobs.py missing"})
    try:
        if step == "prepare_input":
            result = mod.prepare_input(inbox=inbox)
        elif step == "verify_input":
            result = mod.verify_input(inbox=inbox)
        elif step == "interpret_complaint":
            result = mod.interpret_complaint(inbox=inbox)
        elif step == "revise":
            result = mod.revise(inbox=inbox, task_id=task_id)
        else:
            result = {"ok": False, "error": "unknown_step"}
    except Exception as exc:  # noqa: BLE001 — child process boundary
        result = {"ok": False, "error": str(exc)}
    return _emit_worker(step, result)


def _run_legacy(inbox: Path, task_id: str) -> int:
    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    worklog = {
        "task_id": task_id,
        "worker": "scripts/worker_run_task.py",
        "started_utc": utc(),
        "steps": [],
    }
    mod = _load_jobs(inbox, task_id)
    if mod is None:
        worklog["steps"].append({"step": "load_jobs", "ok": False, "error": "worker_jobs.py missing"})
        (out / "worklog.json").write_text(json.dumps(worklog, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "error": "worker_jobs.py missing", "task_id": task_id}, indent=2))
        return 1
    result = mod.run(inbox=inbox, out=out, task_id=task_id)
    worklog["steps"].append({"step": "run", "result": result})
    worklog["finished_utc"] = utc()
    (out / "worklog.json").write_text(json.dumps(worklog, indent=2), encoding="utf-8")
    print(json.dumps({"ok": bool(result.get("ok")), "task_id": task_id, "result": result}, indent=2))
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--inbox", default=None)
    parser.add_argument("--step", choices=("all",) + WORKER_STEPS, default="all")
    args = parser.parse_args(argv)
    tid = args.task_id
    inbox = Path(args.inbox).resolve() if args.inbox else (ROOT / "task_inbox" / tid)
    if not inbox.is_dir():
        print(json.dumps({"ok": False, "error": "missing_inbox", "task_id": tid}))
        return 2

    dispatch_path = inbox / "dispatch.json"
    if not dispatch_path.exists():
        print(json.dumps({"ok": False, "error": "no_dispatch", "task_id": tid}))
        return 2
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    if dispatch.get("task_id") != tid:
        print(json.dumps({"ok": False, "error": "task_id_mismatch", "task_id": tid}))
        return 2

    blocked_pipeline = tid in BLOCKED_TASK_IDS and (
        args.step != "all" or dispatch.get("mode") == "reject_then_revise"
    )
    if blocked_pipeline:
        print(json.dumps({"ok": False, "error": "refused_task_id", "task_id": tid}))
        return 3

    if args.step != "all":
        return _run_worker_step(inbox, tid, args.step)

    if dispatch.get("mode") == "reject_then_revise":
        started = utc()
        from control_plane.reject_revise import orchestrate

        result = orchestrate(inbox=inbox, repo_root=ROOT)
        if result.get("error") == "refused_task_id":
            print(json.dumps({"ok": False, "error": "refused_task_id", "task_id": tid}))
            return 3
        out = inbox / "deliverables"
        out.mkdir(parents=True, exist_ok=True)
        worklog = {
            "task_id": tid,
            "worker_entry": "scripts/worker_run_task.py",
            "mode": "reject_then_revise",
            "paid_api_called": False,
            "started_utc": started,
            "finished_utc": utc(),
            "result": result,
        }
        (out / "worklog.json").write_text(json.dumps(worklog, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": bool(result.get("ok")), "task_id": tid, "result": result}, indent=2))
        return 0 if result.get("ok") else 1

    if dispatch.get("mode") == "model_involved_semantic_revision":
        started = utc()
        from control_plane.semantic_revise import orchestrate

        result = orchestrate(inbox=inbox, repo_root=ROOT)
        out = inbox / "deliverables"
        out.mkdir(parents=True, exist_ok=True)
        worklog = {
            "task_id": tid,
            "worker_entry": "scripts/worker_run_task.py",
            "mode": "model_involved_semantic_revision",
            "paid_api_called": bool(result.get("paid_api_called")),
            "started_utc": started,
            "finished_utc": utc(),
            "result": result,
        }
        (out / "worklog.json").write_text(json.dumps(worklog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"ok": bool(result.get("ok")), "task_id": tid, "result": result}, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    return _run_legacy(inbox, tid)


if __name__ == "__main__":
    raise SystemExit(main())
