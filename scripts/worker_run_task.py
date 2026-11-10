#!/usr/bin/env python3
"""Product Worker entry — run one task_id from task_inbox (L2 path).

  PYTHONPATH=. python3 scripts/worker_run_task.py --task-id DS-T2-20261110

No network. A task module with JOB_SPECS and execute_job is resumed from
state/checkpoint.json after SIGKILL. Other tasks keep the single run() call.

AISTUDIO_INBOX_ROOT isolates tests. The DS resume command does not set it.
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
sys.path.insert(0, str(ROOT))


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    args = ap.parse_args()
    tid = args.task_id
    override = os.environ.get("AISTUDIO_INBOX_ROOT", "").strip()
    inbox_root = Path(override) if override else ROOT / "task_inbox"
    inbox = inbox_root / tid
    if not inbox.is_dir():
        print(json.dumps({"ok": False, "error": "missing_inbox", "task_id": tid}))
        return 2

    dispatch_path = inbox / "dispatch.json"
    if not dispatch_path.exists():
        print(json.dumps({"ok": False, "error": "no_dispatch", "task_id": tid}))
        return 2

    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    worklog = {
        "task_id": tid,
        "worker": "scripts/worker_run_task.py",
        "started_utc": utc(),
        "steps": [],
    }

    jobs_py = inbox / "worker_jobs.py"
    if not jobs_py.exists():
        worklog["steps"].append({"step": "load_jobs", "ok": False, "error": "worker_jobs.py missing"})
        (out / "worklog.json").write_text(json.dumps(worklog, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": "worker_jobs.py missing", "task_id": tid}, indent=2))
        return 1

    spec = importlib.util.spec_from_file_location(f"worker_jobs_{tid}", jobs_py)
    if spec is None or spec.loader is None:
        print(json.dumps({"ok": False, "error": "worker_jobs.py unreadable", "task_id": tid}))
        return 1
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "JOB_SPECS") and hasattr(mod, "execute_job"):
        from control_plane.worker_resume import run_resumable

        result = run_resumable(module=mod, inbox=inbox, out=out, task_id=tid)
    else:
        result = mod.run(inbox=inbox, out=out, task_id=tid)
    worklog["steps"].append({"step": "run", "result": result})
    worklog["finished_utc"] = utc()
    (out / "worklog.json").write_text(json.dumps(worklog, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": bool(result.get("ok")), "task_id": tid, "result": result}, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
