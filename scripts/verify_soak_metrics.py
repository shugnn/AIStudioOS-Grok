#!/usr/bin/env python3
"""Independent read-only check: metrics.json vs summary.jsonl.

Does not run Worker/L1. Exit 0 if consistent within tolerance.

  py -3 scripts/verify_soak_metrics.py
  py -3 scripts/verify_soak_metrics.py --since 2026-10-29T14:07:00Z
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS = ROOT / "docs" / "progress" / "soak_2h" / "metrics.json"
DEFAULT_SUMMARY = ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    ap.add_argument("--since", type=str, default="")
    ap.add_argument("--until", type=str, default="")
    args = ap.parse_args()

    if not args.metrics.is_file():
        print(json.dumps({"ok": False, "error": "metrics_missing", "path": str(args.metrics)}))
        return 1
    if not args.summary.is_file():
        print(json.dumps({"ok": False, "error": "summary_missing", "path": str(args.summary)}))
        return 1

    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for line in args.summary.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = str(r.get("utc", ""))
        if args.since and u < args.since:
            continue
        if args.until and u > args.until:
            continue
        # if metrics has segment bounds and no CLI filter, prefer segment
        rows.append(r)

    if not args.since and metrics.get("segment_first_utc"):
        lo = str(metrics["segment_first_utc"])
        hi = str(metrics.get("segment_last_utc") or "")
        rows = [
            r
            for r in rows
            if str(r.get("utc", "")) >= lo and (not hi or str(r.get("utc", "")) <= hi)
        ]

    exit0 = sum(1 for r in rows if r.get("exit") == 0)
    work = sum(1 for r in rows if r.get("with_work") is True)
    idle = sum(1 for r in rows if r.get("idle") is True)
    n = len(rows)

    checks = {
        "cycles_ran": (metrics.get("cycles_ran"), n),
        "cycles_exit0": (metrics.get("cycles_exit0"), exit0),
        "cycles_with_work": (metrics.get("cycles_with_work"), work),
        "cycles_idle": (metrics.get("cycles_idle"), idle),
    }
    mismatches = {k: {"metrics": a, "summary": b} for k, (a, b) in checks.items() if a != b}

    # soft: planned >= ran
    planned = metrics.get("cycles_planned")
    planned_ok = planned is None or (isinstance(planned, int) and planned >= n)

    ok = len(mismatches) == 0 and planned_ok and n > 0
    out = {
        "ok": ok,
        "summary_rows": n,
        "checks": {k: {"metrics": a, "summary": b, "match": a == b} for k, (a, b) in checks.items()},
        "mismatches": mismatches,
        "planned_ok": planned_ok,
        "sha_full_metrics": metrics.get("sha_full"),
        "rebuilt_from_summary": metrics.get("rebuilt_from_summary"),
        "note": "Independent of Worker; read-only file check.",
    }
    print(json.dumps(out, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
