#!/usr/bin/env python3
"""Product Worker entry — run by task_id (L2 path).

  PYTHONPATH=. python scripts/worker_run_task.py --task-id DS-T1-20261108

Before it reports whether a task exists, the entry check reads Issue #9
comments (read-only GitHub API, $0) and ``task_inbox/``. The job module
itself does not open the network. ``AISTUDIO_OFFLINE_ENTRY=1`` skips the
comment read; that mode reports the check as unresolved and does not invent
a ruling or an empty queue.

Does not start the L2-2 clock. Does not claim production 7×24.
Pre-authored one-off notebooks are not this path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ds_issue9


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_entry_sync() -> ds_issue9.Issue9Sync:
    if os.environ.get("AISTUDIO_OFFLINE_ENTRY") == "1":
        return ds_issue9.issue9_failure(
            "offline_entry",
            "worker execution skipped Issue #9 sync; no ruling invented; do not treat the queue as empty",
        )
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return ds_issue9.sync_issue9(token)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    args = ap.parse_args()
    tid = args.task_id
    inbox_root = ROOT / "task_inbox"
    inbox = inbox_root / tid
    sync = load_entry_sync()
    inbox_ids = ds_issue9.inbox_task_ids(inbox_root)
    entry = ds_issue9.classify_entry(tid, inbox.is_dir(), sync)
    note_rejected = None
    try:
        status_note = ds_issue9.build_heartbeat_note(
            sync,
            inbox_ids,
            utc=utc(),
            next_wake="",
        )
    except ds_issue9.StaleNoteError as exc:
        status_note = None
        note_rejected = {"reason": exc.reason}
    base = {
        "task_id": tid,
        "entry": entry,
        "status_note": status_note,
        "note_rejected": note_rejected,
        "issue9_rulings": {key: value.verdict for key, value in sync.rulings.items()} if sync.ok else {},
        "issue9_sync_error": sync.error_code,
        "production_7x24": ds_issue9.PRODUCTION_7X24,
    }
    if not inbox.is_dir():
        if entry["state"] == "issue_comment_only":
            error = "task_card_only_in_issue_comment"
        elif entry["state"] == "unresolved":
            error = "missing_inbox_issue_sync_unresolved"
        else:
            error = "missing_inbox"
        print(json.dumps({"ok": False, "error": error, **base}, ensure_ascii=False))
        return 2

    # Dispatch marker
    dispatch_path = inbox / "dispatch.json"
    if not dispatch_path.exists():
        print(json.dumps({"ok": False, "error": "no_dispatch", **base}, ensure_ascii=False))
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
        print(json.dumps({"ok": False, "error": "worker_jobs.py missing", **base}, indent=2, ensure_ascii=False))
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
    print(json.dumps({"ok": bool(result.get("ok")), "result": result, **base}, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
