#!/usr/bin/env python3
"""Product Worker entry — run by task_id (L2 path).

  PYTHONPATH=. python scripts/worker_run_task.py --task-id DS-T1-20261108

Does not use network. Pre-authored one-off notebooks are not this path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    args = ap.parse_args()
    tid = args.task_id
    inbox = ROOT / "task_inbox" / tid
    if not inbox.is_dir():
        print(json.dumps({"ok": False, "error": "missing_inbox", "task_id": tid}))
        return 2

    # Dispatch marker
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

    # Import task-specific worker module if present
    mod_name = f"task_inbox.{tid.replace('-', '_')}.worker_jobs"
    # Prefer local file path under inbox
    jobs_py = inbox / "worker_jobs.py"
    if not jobs_py.exists():
        worklog["steps"].append({"step": "load_jobs", "ok": False, "error": "worker_jobs.py missing"})
        (out / "worklog.json").write_text(json.dumps(worklog, indent=2), encoding="utf-8")
        print(json.dumps({"ok": False, "error": "worker_jobs.py missing", "task_id": tid}, indent=2))
        return 1

    import importlib.util

    spec = importlib.util.spec_from_file_location(f"worker_jobs_{tid}", jobs_py)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = mod.run(inbox=inbox, out=out, task_id=tid)
    worklog["steps"].append({"step": "run", "result": result})
    worklog["finished_utc"] = utc()
    (out / "worklog.json").write_text(json.dumps(worklog, indent=2), encoding="utf-8")
    print(json.dumps({"ok": bool(result.get("ok")), "task_id": tid, "result": result}, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
