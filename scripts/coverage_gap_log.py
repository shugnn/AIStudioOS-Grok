#!/usr/bin/env python3
"""Append one supervision gap record. Does not start a soak or a 72h clock.

Bands follow FOUNDER R2: ok below 13s, yellow from 13s through 5min, red above 5min.
A line records a gap only. It does not say the soak is complete, accepted, or running.

  python3 scripts/coverage_gap_log.py --gap-seconds 30 --source operator_sample --out /tmp/gaps.jsonl
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "aistudioos-grok.coverage-gap.v1"
YELLOW_MIN_SECONDS = 13.0
RED_MIN_SECONDS = 300.0  # red is strictly greater than 5 min
BANDS = {"ok", "yellow", "red"}
SOURCES = {
    "soak_summary_live",
    "soak_summary_path",
    "runner_glob_live",
    "runner_glob_unconfirmed",
    "operator_sample",
}


class GapLogError(ValueError):
    """Gap record is incomplete or would over-claim."""


def classify_band(
    gap_seconds: float,
    *,
    yellow_min: float = YELLOW_MIN_SECONDS,
    red_min: float = RED_MIN_SECONDS,
) -> str:
    """Return ok, yellow, or red. 300s is yellow. Above 300s is red."""
    if isinstance(gap_seconds, bool) or not isinstance(gap_seconds, (int, float)):
        raise GapLogError("gap_seconds must be a number")
    if gap_seconds < 0:
        raise GapLogError("gap_seconds must be >= 0")
    if isinstance(yellow_min, bool) or not isinstance(yellow_min, (int, float)):
        raise GapLogError("yellow_min must be a number")
    if isinstance(red_min, bool) or not isinstance(red_min, (int, float)):
        raise GapLogError("red_min must be a number")
    if red_min <= yellow_min:
        raise GapLogError("red_min must be greater than yellow_min")
    if gap_seconds > red_min:
        return "red"
    if gap_seconds >= yellow_min:
        return "yellow"
    return "ok"


def watch_source(*, runner_glob: bool, live_dut: bool) -> str:
    """Name the watch target. live_dut is an operator claim, not proof of liveness."""
    if live_dut and runner_glob:
        return "runner_glob_live"
    if live_dut:
        return "soak_summary_live"
    if runner_glob:
        return "runner_glob_unconfirmed"
    return "soak_summary_path"


def should_append(band: str, previous_band: str | None) -> bool:
    """Yellow and red are always logged. Ok is logged only when a gap recovers."""
    if band not in BANDS:
        raise GapLogError(f"band must be one of {sorted(BANDS)}")
    if band in {"yellow", "red"}:
        return True
    return previous_band in {"yellow", "red"}


def parse_timestamp(value: str, *, field: str = "timestamp") -> datetime:
    text = value.strip()
    if not text:
        raise GapLogError(f"{field}: empty timestamp")
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise GapLogError(f"{field}: unparseable timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise GapLogError(f"{field}: naive timestamp rejected: {value!r}")
    return parsed.astimezone(timezone.utc)


def utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(
    *,
    gap_seconds: float | None,
    source: str,
    timestamp: str,
    mono_seconds: float | None = None,
    signal: str = "present",
    yellow_min: float = YELLOW_MIN_SECONDS,
    red_min: float = RED_MIN_SECONDS,
) -> dict[str, Any]:
    """Build one gap line. Band is derived. The line cannot mark a soak complete."""
    if source not in SOURCES:
        raise GapLogError(f"source must be one of {sorted(SOURCES)}")
    if signal not in {"present", "missing"}:
        raise GapLogError("signal must be present or missing")
    stamp = utc_z(parse_timestamp(timestamp))
    if mono_seconds is not None and (
        isinstance(mono_seconds, bool) or not isinstance(mono_seconds, (int, float)) or mono_seconds < 0
    ):
        raise GapLogError("mono_seconds must be a non-negative number or null")
    if signal == "missing":
        if gap_seconds is not None:
            raise GapLogError("a missing signal has no measured gap_seconds")
        band = "red"
        measured: float | None = None
    else:
        if gap_seconds is None:
            raise GapLogError("gap_seconds is required when the signal is present")
        band = classify_band(gap_seconds, yellow_min=yellow_min, red_min=red_min)
        measured = float(gap_seconds)
    return {
        "schema": SCHEMA,
        "timestamp": stamp,
        "gap_seconds": measured,
        "band": band,
        "source": source,
        "signal": signal,
        "coverage_gap": band == "yellow",
        "mono_seconds": None if mono_seconds is None else float(mono_seconds),
        "yellow_min_seconds": float(yellow_min),
        "red_exclusive_min_seconds": float(red_min),
        "implies_soak_complete": False,
        "clock_effect": "none",
    }


def append_record(path: Path, record: dict[str, Any]) -> None:
    if record.get("schema") != SCHEMA:
        raise GapLogError("refusing to append a record that is not a coverage gap")
    if record.get("implies_soak_complete") is not False or record.get("clock_effect") != "none":
        raise GapLogError("refusing to append a record that claims soak progress")
    if record.get("band") not in BANDS:
        raise GapLogError("refusing to append a record with an unknown band")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gap-seconds", type=float, required=True)
    ap.add_argument("--source", choices=sorted(SOURCES), required=True)
    ap.add_argument("--timestamp", default=None)
    ap.add_argument("--mono-seconds", type=float, default=None)
    ap.add_argument("--out", type=Path, default=None, help="append here; omit to print only")
    args = ap.parse_args(argv)
    timestamp = args.timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        record = build_record(
            gap_seconds=args.gap_seconds,
            source=args.source,
            timestamp=timestamp,
            mono_seconds=args.mono_seconds,
        )
    except GapLogError as exc:
        print(json.dumps({"ok": False, "error": "invalid_gap", "detail": str(exc)}))
        return 2
    if args.out is not None:
        append_record(args.out, record)
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
