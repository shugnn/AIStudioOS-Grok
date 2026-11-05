#!/usr/bin/env python3
"""Supervision monitor (FOUNDER R1–R3).

Watches progress signal mtime. Yellow 13s–5min: coverage_gap only.
Red >5min: exit 2 (supervision failure) unless --never-red (DUT-only test).

Injection: create docs/progress/SUPERVISION_PAUSE to freeze checks (simulates
monitor drop while DUT continues). Remove file to resume.

  python3 scripts/supervision_monitor.py --runner-glob --interval 30
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "docs" / "progress"
GAP_LOG = PROGRESS / "coverage_gaps.jsonl"
PAUSE = PROGRESS / "SUPERVISION_PAUSE"
ALERT = PROGRESS / "STALL_ALERT.json"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def signal_mtime(runner_glob: bool, summary: Path) -> tuple[float, str]:
    if runner_glob:
        runners = sorted(
            PROGRESS.glob("runner-*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if not runners:
            return 0.0, "no_runner"
        return runners[0].stat().st_mtime, str(runners[0])
    if not summary.is_file():
        return 0.0, "no_summary"
    return summary.stat().st_mtime, str(summary)


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--yellow-seconds", type=float, default=13.0)
    ap.add_argument("--red-seconds", type=float, default=300.0)
    ap.add_argument("--runner-glob", action="store_true")
    ap.add_argument("--summary", type=Path, default=PROGRESS / "soak_2h" / "summary.jsonl")
    ap.add_argument("--max-runtime", type=float, default=0.0, help="0=forever")
    ap.add_argument("--never-red", action="store_true", help="only log yellow, never exit red")
    args = ap.parse_args()

    PROGRESS.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    last_level = "green"
    emit({"event": "monitor_start", "utc": utc(), "runner_glob": args.runner_glob})

    while True:
        if args.max_runtime > 0 and (time.monotonic() - t0) >= args.max_runtime:
            emit({"event": "max_runtime", "utc": utc()})
            return 0

        if PAUSE.is_file():
            emit({"event": "paused", "utc": utc()})
            time.sleep(args.interval)
            continue

        mtime, path = signal_mtime(args.runner_glob, args.summary)
        now = time.time()
        age = (now - mtime) if mtime > 0 else 1e9

        if age >= args.red_seconds:
            level = "red"
        elif age >= args.yellow_seconds:
            level = "yellow"
        else:
            level = "green"

        if level != last_level or level != "green":
            row = {
                "utc": utc(),
                "mono": round(time.monotonic() - t0, 3),
                "level": level,
                "age_seconds": round(age, 3),
                "path": path,
            }
            if level == "yellow":
                row["coverage_gap"] = True
                with open(GAP_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            emit({"event": "level", **row})
            last_level = level

        if level == "red" and not args.never_red:
            payload = {"supervision_failure": True, **row}
            ALERT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            emit({"event": "red_exit", "utc": utc()})
            return 2

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
