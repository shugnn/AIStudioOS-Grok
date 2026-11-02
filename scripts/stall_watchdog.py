#!/usr/bin/env python3
"""Detect soak/L1 stall: no new summary.jsonl line within max_idle_minutes.

Exit 0 = healthy (recent progress or no summary yet with --allow-missing).
Exit 1 = stall detected (writes docs/progress/STALL_ALERT.json).
Exit 2 = summary missing and not allowed.

  py -3 scripts/stall_watchdog.py --max-idle-minutes 15
  py -3 scripts/stall_watchdog.py --summary docs/progress/soak_2h/summary.jsonl
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl"
ALERT = ROOT / "docs" / "progress" / "STALL_ALERT.json"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def last_row_mtime_and_utc(path: Path) -> tuple[float, str | None, int]:
    if not path.is_file():
        return 0.0, None, 0
    mtime = path.stat().st_mtime
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    n = 0
    last_utc = None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        n = sum(1 for x in lines if x.strip())
        try:
            o = json.loads(line)
            last_utc = str(o.get("utc") or "") or None
        except json.JSONDecodeError:
            last_utc = None
        break
    return mtime, last_utc, n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    ap.add_argument("--max-idle-minutes", type=float, default=15.0)
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    if not args.summary.is_file():
        payload = {"ok": False, "error": "summary_missing", "path": str(args.summary), "utc": utc()}
        print(json.dumps(payload, indent=2))
        return 0 if args.allow_missing else 2

    mtime, last_utc, nrows = last_row_mtime_and_utc(args.summary)
    age_s = time.time() - mtime
    max_s = args.max_idle_minutes * 60.0
    stalled = age_s > max_s

    payload = {
        "ok": not stalled,
        "utc": utc(),
        "summary": str(args.summary),
        "rows_est": nrows,
        "last_row_utc": last_utc,
        "file_age_seconds": round(age_s, 1),
        "max_idle_seconds": max_s,
        "stalled": stalled,
    }
    print(json.dumps(payload, indent=2))

    if stalled:
        ALERT.parent.mkdir(parents=True, exist_ok=True)
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
