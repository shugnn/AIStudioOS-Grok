#!/usr/bin/env python3
"""Rebuild metrics.json from summary.jsonl when a soak dies without final metrics.

Example (FOUNDER-20261029-SOAK-24H recovery):
  py -3 scripts/rebuild_soak_metrics_from_summary.py \
    --since 2026-10-29T14:07:00Z \
    --planned 1440 \
    --sha e3e884615fc8118c882ad1ade4da250adb418846 \
    --idle-policy reseed \
    --via-l1
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl"
DEFAULT_OUT = ROOT / "docs" / "progress" / "soak_2h" / "metrics.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--since", type=str, default="", help="ISO utc lower bound inclusive")
    ap.add_argument("--until", type=str, default="", help="ISO utc upper bound inclusive")
    ap.add_argument("--planned", type=int, default=0)
    ap.add_argument("--sha", type=str, default="")
    ap.add_argument("--idle-policy", type=str, default="unknown")
    ap.add_argument("--via-l1", action="store_true")
    ap.add_argument("--stopped-early", type=str, default="rebuilt_from_summary_no_final_metrics")
    args = ap.parse_args()

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
        rows.append(r)

    if not rows:
        print(json.dumps({"error": "no_rows", "summary": str(args.summary)}))
        return 1

    exit0 = sum(1 for r in rows if r.get("exit") == 0)
    work = sum(1 for r in rows if r.get("with_work") is True)
    idle = sum(1 for r in rows if r.get("idle") is True)
    sha = args.sha or str(rows[0].get("sha_full") or "unknown")
    planned = args.planned or max(int(r.get("cycle") or 0) for r in rows)

    metrics = {
        "utc_end": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha_short": sha[:7] if len(sha) >= 7 else sha,
        "sha_full": sha,
        "via_l1": bool(args.via_l1),
        "idle_policy": args.idle_policy,
        "cycles_planned": planned,
        "cycles_ran": len(rows),
        "cycles_exit0": exit0,
        "cycles_with_work": work,
        "cycles_idle": idle,
        "tasks_done_unique_est": work,
        "stopped_early": args.stopped_early,
        "final": True,
        "rebuilt_from_summary": True,
        "segment_first_utc": rows[0].get("utc"),
        "segment_last_utc": rows[-1].get("utc"),
        "note": (
            "Rebuilt from summary.jsonl because process exited without metrics.json. "
            "cycles_exit0 is process success only; business progress is cycles_with_work."
        ),
        "evidence_binding": "medium_plus",
        "paths": {
            "summary_jsonl": str(args.summary),
            "metrics_json": str(args.out),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    tmp.replace(args.out)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
