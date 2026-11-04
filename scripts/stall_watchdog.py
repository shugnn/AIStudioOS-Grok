#!/usr/bin/env python3
"""Detect stall: no fresh activity under progress dir within max_idle_minutes.

Modes:
  --summary PATH     legacy soak summary.jsonl (default)
  --runner-glob      watch newest docs/progress/runner-*.json mtime (L1 duty)

Exit 0 healthy; 1 stall; 2 missing target.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl"
PROGRESS = ROOT / "docs" / "progress"
ALERT = PROGRESS / "STALL_ALERT.json"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, default=None)
    ap.add_argument(
        "--runner-glob",
        action="store_true",
        help="watch newest runner-*.json under docs/progress (for L1 schtasks duty)",
    )
    ap.add_argument("--max-idle-minutes", type=float, default=15.0)
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    target = "summary"
    mtime = 0.0
    last_utc = None
    nrows = 0
    path_s = ""

    if args.runner_glob:
        target = "runner_glob"
        runners = sorted(PROGRESS.glob("runner-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runners:
            payload = {"ok": False, "error": "no_runner_json", "utc": utc()}
            print(json.dumps(payload, indent=2))
            return 0 if args.allow_missing else 2
        newest = runners[0]
        path_s = str(newest)
        mtime = newest.stat().st_mtime
        try:
            o = json.loads(newest.read_text(encoding="utf-8"))
            last_utc = str(o.get("utc") or "") or None
        except (OSError, json.JSONDecodeError):
            last_utc = None
        nrows = len(runners)
    else:
        summary = args.summary or DEFAULT_SUMMARY
        path_s = str(summary)
        if not summary.is_file():
            payload = {"ok": False, "error": "summary_missing", "path": path_s, "utc": utc()}
            print(json.dumps(payload, indent=2))
            return 0 if args.allow_missing else 2
        mtime = summary.stat().st_mtime
        lines = summary.read_text(encoding="utf-8", errors="replace").splitlines()
        nrows = sum(1 for x in lines if x.strip())
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                last_utc = str(json.loads(line).get("utc") or "") or None
            except json.JSONDecodeError:
                last_utc = None
            break

    age_s = time.time() - mtime
    max_s = args.max_idle_minutes * 60.0
    stalled = age_s > max_s
    payload = {
        "ok": not stalled,
        "utc": utc(),
        "target": target,
        "path": path_s,
        "rows_or_files": nrows,
        "last_row_utc": last_utc,
        "file_age_seconds": round(age_s, 1),
        "max_idle_seconds": max_s,
        "stalled": stalled,
    }
    print(json.dumps(payload, indent=2))
    if stalled:
        ALERT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return 1
    if ALERT.is_file():
        try:
            ALERT.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
