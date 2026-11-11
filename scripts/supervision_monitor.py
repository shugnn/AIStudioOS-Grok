#!/usr/bin/env python3
"""Supervision monitor (FOUNDER R1–R3).

Watches a progress-signal mtime and appends gap lines through coverage_gap_log.
Yellow is 13s through 5min (coverage_gap, not a business FAIL).
Red is older than 5min and exits 2 unless --never-red.

--live-dut is an operator claim that the watch file is the live DUT.
Without it, the source is soak_summary_path or runner_glob_unconfirmed.
The default summary path is not treated as a live 72h soak.

Injection: create docs/progress/SUPERVISION_PAUSE to freeze checks.
This process does not start soak_2h.py and does not register scheduled tasks.

  python3 scripts/supervision_monitor.py --runner-glob --interval 30
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import coverage_gap_log as gaplog

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "docs" / "progress"
GAP_LOG = PROGRESS / "coverage_gaps.jsonl"
PAUSE = PROGRESS / "SUPERVISION_PAUSE"
ALERT = PROGRESS / "STALL_ALERT.json"
LEVEL_FOR_BAND = {"ok": "green", "yellow": "yellow", "red": "red"}


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


def observe(
    *,
    age_seconds: float | None,
    signal: str,
    previous_band: str | None,
    source: str,
    timestamp: str,
    mono_seconds: float | None,
    log_path: Path | None,
    yellow_seconds: float = gaplog.YELLOW_MIN_SECONDS,
    red_seconds: float = gaplog.RED_MIN_SECONDS,
) -> dict[str, Any]:
    """Classify one sample and append when the band should be kept."""
    record = gaplog.build_record(
        gap_seconds=age_seconds,
        source=source,
        timestamp=timestamp,
        mono_seconds=mono_seconds,
        signal=signal,
        yellow_min=yellow_seconds,
        red_min=red_seconds,
    )
    appended = False
    if gaplog.should_append(record["band"], previous_band) and log_path is not None:
        gaplog.append_record(log_path, record)
        appended = True
    return {
        "band": record["band"],
        "level": LEVEL_FOR_BAND[record["band"]],
        "record": record,
        "appended": appended,
        "red_exit": record["band"] == "red",
        "coverage_gap": record["coverage_gap"],
    }


def build_parser() -> argparse.ArgumentParser:
    """Flag surface only. Calling this does not watch a file or start a soak."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--yellow-seconds", type=float, default=gaplog.YELLOW_MIN_SECONDS)
    ap.add_argument("--red-seconds", type=float, default=gaplog.RED_MIN_SECONDS)
    ap.add_argument("--runner-glob", action="store_true")
    ap.add_argument("--summary", type=Path, default=PROGRESS / "soak_2h" / "summary.jsonl")
    ap.add_argument("--max-runtime", type=float, default=0.0, help="0=forever")
    ap.add_argument("--never-red", action="store_true", help="log red, but do not exit")
    ap.add_argument(
        "--live-dut",
        action="store_true",
        help="claim the watch file is the live DUT (does not start a soak)",
    )
    ap.add_argument("--gap-log", type=Path, default=GAP_LOG)
    return ap


def main() -> int:
    args = build_parser().parse_args()

    PROGRESS.mkdir(parents=True, exist_ok=True)
    source = gaplog.watch_source(runner_glob=args.runner_glob, live_dut=args.live_dut)
    t0 = time.monotonic()
    last_level = "green"
    last_band: str | None = None
    emit(
        {
            "event": "monitor_start",
            "utc": utc(),
            "runner_glob": args.runner_glob,
            "source": source,
            "live_dut_claimed": args.live_dut,
        }
    )

    while True:
        if args.max_runtime > 0 and (time.monotonic() - t0) >= args.max_runtime:
            emit({"event": "max_runtime", "utc": utc()})
            return 0

        if PAUSE.is_file():
            emit({"event": "paused", "utc": utc()})
            time.sleep(args.interval)
            continue

        mtime, path = signal_mtime(args.runner_glob, args.summary)
        if mtime > 0:
            signal = "present"
            age: float | None = time.time() - mtime
        else:
            signal = "missing"
            age = None
        seen = observe(
            age_seconds=age,
            signal=signal,
            previous_band=last_band,
            source=source,
            timestamp=utc(),
            mono_seconds=round(time.monotonic() - t0, 3),
            log_path=args.gap_log,
            yellow_seconds=args.yellow_seconds,
            red_seconds=args.red_seconds,
        )
        level = seen["level"]
        record = seen["record"]
        if level != last_level or level != "green":
            row = {
                "utc": record["timestamp"],
                "mono": record["mono_seconds"],
                "level": level,
                "band": record["band"],
                "age_seconds": record["gap_seconds"],
                "path": path,
                "source": source,
            }
            if record["coverage_gap"]:
                row["coverage_gap"] = True
            emit({"event": "level", **row})
            last_level = level
        last_band = record["band"]

        if seen["red_exit"] and not args.never_red:
            payload = {"supervision_failure": True, "implies_soak_complete": False, **record, "path": path}
            ALERT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            emit({"event": "red_exit", "utc": utc(), "source": source})
            return 2

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
