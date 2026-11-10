#!/usr/bin/env python3
"""Offline scorer for the Grok duty-cycle L2-2 72h wall soak.

Reads a capture bundle (schema aistudioos-grok.l2-2.capture.v1) and writes an
honest report. This tool does not start a clock, does not register scheduled
tasks, and never emits L2-2 PASS or production 7x24 acceptance. A sum of ended
SHORT walls does not count. Stitching sequential or restarted soak invocations
into one capture does not count, even when the stitched span reaches 259200.

Exit 0: an honest NOT_STARTED or INCOMPLETE report was produced.
Exit 2: the capture or the report failed validation.

  python3 scripts/l2_2_score.py --capture tests/fixtures/l2_2/scaffold_clock_not_started.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import coverage_gap_log as gaplog

SCHEMA_CAPTURE = "aistudioos-grok.l2-2.capture.v1"
SCHEMA_REPORT = "aistudioos-grok.l2-2.report.v1"
WALL_REQUIRED_SECONDS = 259200  # 72 * 3600, monotonic
WALL_MATCH_TOLERANCE = 0.001

# L2-4 historical window. Scaffold fixtures must stay outside it.
INCIDENT_START = datetime(2026, 11, 3, tzinfo=timezone.utc)
INCIDENT_END = datetime(2026, 11, 6, tzinfo=timezone.utc)

L2_4_CROSSLINK = {
    "status": "INCOMPLETE",
    "window": "2026-11-03..06",
    "pr": "https://github.com/shugnn/AIStudioOS-Grok/pull/11",
    "tip": "931758cb7487d8c8ac1697f1b3ad1e2fa7610ef6",
    "relitigated": False,
}

ALLOWED_RUNNER_KINDS = {"soak_2h_via_l1", "existing_local_loop"}
FORBIDDEN_RUNNER_KINDS = {"interactive_schtasks", "logon_schtasks", "schtasks_new"}
RUNNER_KINDS = ALLOWED_RUNNER_KINDS | FORBIDDEN_RUNNER_KINDS | {"none"}
WATCH_FOR_KIND = {
    "soak_2h_via_l1": "soak_summary_live",
    "existing_local_loop": "runner_glob_live",
}
ENDED_WATCH_TARGETS = {"ended_experiment", "stale_summary"}
# Explicit sum/product sources. A capture may name them so the scorer can
# refuse the claim. They are not one continuous monotonic soak.
ADDITIVE_WALL_SOURCES = frozenset(
    {
        "sum",
        "summed",
        "additive",
        "stacked",
        "product",
        "multiplied",
        "historical_sum",
        "hours_times_count",
    }
)
ADDITIVE_FLAGS = ("additive", "summed", "stacked")
ADDITIVE_LIST_KEYS = ("components", "summed_from", "additive_walls", "historical_walls")
ADDITIVE_COUNT_KEYS = ("sum_of_24h", "added_24h_count", "times_24h")
SHORT_DAY_SECONDS = 86400.0
# Explicit stitch/restart sources. A capture may name them so the scorer can
# refuse the claim. Two invocations are not one live soak process.
STITCH_WALL_SOURCES = frozenset(
    {
        "stitch",
        "stitched",
        "chained",
        "concatenated",
        "restarted",
        "restart",
        "sequential",
        "process_boundary",
    }
)
WALL_SOURCES = {"unset", "monotonic", "cycles_times_interval", "utc_span"} | set(ADDITIVE_WALL_SOURCES) | set(
    STITCH_WALL_SOURCES
)
STITCH_FLAGS = ("stitched", "chained", "concatenated", "restarted", "sequential", "wall_reset")
STITCH_LIST_KEYS = ("invocations", "processes", "segments", "stitched_from", "soaks")
WALL_SERIES_KEYS = ("wall_samples", "elapsed_series", "wall_elapsed_series")
START_LIST_KEYS = ("starts", "start_utcs", "start_timestamps")
PID_LIST_KEYS = ("pids", "process_ids")
# In-memory sequential soaks are anchored here, far from the L2-4 window.
STITCH_ANCHOR = datetime(2026, 2, 1, tzinfo=timezone.utc)
HOST_STOPS = {
    "exception",
    "keyboard_interrupt",
    "emergency_stop",
    "emergency_stop_l1",
    "emergency_stop_before_start",
}
YELLOW_MIN_SECONDS = gaplog.YELLOW_MIN_SECONDS
RED_MIN_SECONDS = gaplog.RED_MIN_SECONDS  # gap > 5 min is red; 300s exactly stays yellow

PERMANENT_BLOCKERS = (
    "tool_does_not_accept_l2_2",
    "tool_does_not_start_clock",
    "production_7x24_not_accepted",
    "interactive_registration_founder_gated_out_of_scope",
    "observation_track_has_not_accepted",
)

NEXT_STEPS = (
    "Leave the 2026-11-03..06 L2-4 reconstruction on PR #11. Do not re-capture that window to start L2-2.",
    "Do not register, create, or enable Interactive console scheduled tasks. That is a founder major gate and is not approved by this scaffold.",
    "Keep the 72h clock NOT STARTED until a founder or worker explicitly decides to start the existing non-Interactive local soak.",
    "Before that start, fill docs/progress/l2_2/R2_CHECKLIST.md. Watch the live soak summary.jsonl while soak_2h.py is the DUT (runner-*.json only when the DUT is L1 with no soak). scripts/coverage_gap_log.py appends timestamp, gap_seconds, band (ok below 13s, yellow 13s through 5min, red above 5min), and source. Yellow is not a business FAIL. A gap line does not start the clock or complete the soak.",
    "Only after that explicit start decision, on a host already allowed to run the local soak: PYTHONPATH=. python scripts/soak_2h.py --cycles 5000 --interval 60 --via-l1 --seed 300 --idle-policy reseed --max-wall-seconds 259200",
    "Cycles must be large enough that max-wall stops the process. cycles x interval is not the wall. cycles_exit0 is not business progress. A 86400s wall is not this 72h gate.",
    "Historical SHORT walls are not additive. Ubuntu-24H 86400.001s plus another 86400s, or 86400s times 3, is not one continuous monotonic wall and is not this 72h gate.",
    "Sequential or restarted soak invocations are not one live process. A back-to-back pair of 86400s soaks, three sequential 86400s soaks covering 72h of calendar time, or a wall that resets or goes backwards, is not this 72h gate.",
    "After a real run, score the bundle with scripts/l2_2_score.py. Expect INCOMPLETE. This tool will not emit PASS or accept production 7x24.",
    "An R3 injection receipt is required before any supervision-verified tag. The observation track accepts or rejects. This scorer does not.",
    "Product L2 (task split / worker) stays NOT STARTED. L2-3 mid-run kill recovery is a separate gate.",
)


class CaptureError(ValueError):
    """Capture bundle is missing, mislabeled, or not safe to score."""


def parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise CaptureError(f"{field}: timestamp must be an ISO-8601 string")
    text = value.strip()
    if not text:
        raise CaptureError(f"{field}: empty timestamp")
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise CaptureError(f"{field}: unparseable timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise CaptureError(
            f"{field}: naive timestamp rejected (need UTC offset or Z): {value!r}"
        )
    return parsed.astimezone(timezone.utc)


def utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_bool(doc: dict[str, Any], field: str) -> bool:
    value = doc.get(field)
    if not isinstance(value, bool):
        raise CaptureError(f"{field} must be a bool")
    return value


def _in_incident_window(stamp: datetime) -> bool:
    return INCIDENT_START <= stamp < INCIDENT_END


def load_capture(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaptureError(f"unreadable capture: {path}: {exc}") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CaptureError(f"capture is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise CaptureError("capture root must be an object")
    validate_capture(doc)
    return doc


def validate_capture(doc: dict[str, Any]) -> None:
    if doc.get("schema") != SCHEMA_CAPTURE:
        raise CaptureError(f"schema must be {SCHEMA_CAPTURE}")
    evidence = doc.get("evidence_class")
    if evidence not in {"scaffold", "host_observation"}:
        raise CaptureError("evidence_class must be scaffold or host_observation")
    synthetic = doc.get("synthetic")
    if evidence == "scaffold" and synthetic is not True:
        raise CaptureError("scaffold capture must set synthetic true")
    if evidence == "host_observation" and synthetic is not False:
        raise CaptureError("host_observation must set synthetic false")
    note = doc.get("note")
    if not isinstance(note, str) or not note.strip():
        raise CaptureError("note must be a non-empty string")
    if evidence == "host_observation":
        host = doc.get("host")
        if not isinstance(host, str) or not host.strip():
            raise CaptureError("host_observation requires host")
    elif doc.get("host") is not None and (not isinstance(doc.get("host"), str) or not doc["host"].strip()):
        raise CaptureError("host must be a string or null")

    clock = doc.get("clock")
    if not isinstance(clock, dict):
        raise CaptureError("clock must be an object")
    started = clock.get("started")
    if not isinstance(started, bool):
        raise CaptureError("clock.started must be a bool")
    _validate_clock_bounds(clock, started=started)

    wall = doc.get("wall")
    if not isinstance(wall, dict):
        raise CaptureError("wall must be an object")
    if wall.get("required_seconds") != WALL_REQUIRED_SECONDS:
        raise CaptureError(
            f"wall.required_seconds must be {WALL_REQUIRED_SECONDS} (72h). "
            "Do not shorten the gate to a 24h wall."
        )
    source = wall.get("source")
    if source not in WALL_SOURCES:
        raise CaptureError(f"wall.source must be one of {sorted(WALL_SOURCES)}")
    if started:
        if source == "unset":
            raise CaptureError("a started clock cannot use wall.source unset")
        if not _is_number(wall.get("elapsed_seconds")) or wall["elapsed_seconds"] < 0:
            raise CaptureError("wall.elapsed_seconds must be a non-negative number when started")
        if not _is_int(wall.get("max_wall_seconds")) or wall["max_wall_seconds"] < 0:
            raise CaptureError("wall.max_wall_seconds must be a non-negative int when started")
    else:
        if source != "unset":
            raise CaptureError("a clock that has not started must use wall.source unset")
        if wall.get("elapsed_seconds") is not None or wall.get("max_wall_seconds") is not None:
            raise CaptureError("elapsed and max_wall_seconds must be null when the clock has not started")
    _parse_invocation_list(wall)
    _parse_wall_samples(wall)
    _parse_start_list(wall)
    _parse_pid_list(wall)

    metrics = doc.get("metrics")
    if started:
        if not isinstance(metrics, dict):
            raise CaptureError("metrics object is required when the clock has started")
        _validate_metrics(metrics)
    elif metrics is not None:
        raise CaptureError("metrics must be null when the clock has not started")

    rows = doc.get("summary_rows")
    if not isinstance(rows, list):
        raise CaptureError("summary_rows must be a list")
    if not started and rows:
        raise CaptureError("summary rows require a started clock")
    for index, row in enumerate(rows):
        _validate_summary_row(row, index)

    supervision = doc.get("supervision")
    if not isinstance(supervision, dict):
        raise CaptureError("supervision must be an object")
    _validate_supervision(supervision, started=started)

    runner = doc.get("runner")
    if not isinstance(runner, dict):
        raise CaptureError("runner must be an object")
    _validate_runner(runner)

    if "captured_utc" in doc and doc["captured_utc"] is not None:
        parse_utc(doc["captured_utc"], field="captured_utc")
    sha = doc.get("git_sha")
    if sha is not None and (not isinstance(sha, str) or not sha.strip()):
        raise CaptureError("git_sha must be a non-empty string or null")
    for field in ("claimed_l2_2_status", "claimed_production_7x24"):
        if field in doc and doc[field] is not None and not isinstance(doc[field], str):
            raise CaptureError(f"{field} must be a string or null")

    if evidence == "scaffold":
        _reject_scaffold_incident_dates(doc)


def _validate_clock_bounds(clock: dict[str, Any], *, started: bool) -> None:
    start = clock.get("start_utc")
    end = clock.get("end_utc")
    if started:
        start_dt = parse_utc(start, field="clock.start_utc")
        end_dt = parse_utc(end, field="clock.end_utc")
        if end_dt <= start_dt:
            raise CaptureError("clock.end_utc must be after clock.start_utc")
    else:
        if start is not None or end is not None:
            raise CaptureError("clock bounds must be null when the clock has not started")


def _validate_metrics(metrics: dict[str, Any]) -> None:
    if not isinstance(metrics.get("final"), bool):
        raise CaptureError("metrics.final must be a bool")
    if metrics.get("stopped_early") is not None and not isinstance(metrics.get("stopped_early"), str):
        raise CaptureError("metrics.stopped_early must be a string or null")
    for key in ("cycles_ran", "cycles_exit0", "cycles_with_work", "cycles_idle", "max_wall_seconds"):
        if not _is_int(metrics.get(key)) or metrics[key] < 0:
            raise CaptureError(f"metrics.{key} must be a non-negative int")
    if not _is_number(metrics.get("wall_elapsed_s")) or metrics["wall_elapsed_s"] < 0:
        raise CaptureError("metrics.wall_elapsed_s must be a non-negative number")
    if not isinstance(metrics.get("via_l1"), bool):
        raise CaptureError("metrics.via_l1 must be a bool")


def _validate_summary_row(row: Any, index: int) -> None:
    if not isinstance(row, dict):
        raise CaptureError(f"summary_rows[{index}] must be an object")
    parse_utc(row.get("utc"), field=f"summary_rows[{index}].utc")
    if not isinstance(row.get("with_work"), bool):
        raise CaptureError(f"summary_rows[{index}].with_work must be a bool")
    if not isinstance(row.get("idle"), bool):
        raise CaptureError(f"summary_rows[{index}].idle must be a bool")
    if not _is_int(row.get("exit")):
        raise CaptureError(f"summary_rows[{index}].exit must be an int")


def _validate_supervision(supervision: dict[str, Any], *, started: bool) -> None:
    if not isinstance(supervision.get("r2_declared_before_start"), bool):
        raise CaptureError("supervision.r2_declared_before_start must be a bool")
    receipt = supervision.get("r3_injection_receipt")
    if receipt is not None and not isinstance(receipt, (str, dict)):
        raise CaptureError("supervision.r3_injection_receipt must be a string, object, or null")
    if isinstance(receipt, str) and not receipt.strip():
        raise CaptureError("supervision.r3_injection_receipt string must be non-empty")
    if isinstance(receipt, dict) and (not isinstance(receipt.get("path"), str) or not receipt["path"].strip()):
        raise CaptureError("supervision.r3_injection_receipt.path must be a non-empty string")
    watch = supervision.get("watch_target")
    if watch is not None and not isinstance(watch, str):
        raise CaptureError("supervision.watch_target must be a string or null")
    gaps = supervision.get("coverage_gaps")
    if not isinstance(gaps, list):
        raise CaptureError("supervision.coverage_gaps must be a list")
    if not started and gaps:
        raise CaptureError("coverage gaps require a started clock")
    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            raise CaptureError(f"coverage_gaps[{index}] must be an object")
        _normalized_gap(gap, index)


def _validate_runner(runner: dict[str, Any]) -> None:
    kind = runner.get("kind")
    if kind not in RUNNER_KINDS:
        raise CaptureError(f"runner.kind must be one of {sorted(RUNNER_KINDS)}")
    if not isinstance(runner.get("interactive"), bool):
        raise CaptureError("runner.interactive must be a bool")
    if not isinstance(runner.get("registered_this_run"), bool):
        raise CaptureError("runner.registered_this_run must be a bool")
    names = runner.get("task_names")
    if not isinstance(names, list):
        raise CaptureError("runner.task_names must be a list")
    for index, name in enumerate(names):
        if not isinstance(name, str) or not name.strip():
            raise CaptureError(f"runner.task_names[{index}] must be a non-empty string")


def _reject_scaffold_incident_dates(doc: dict[str, Any]) -> None:
    stamps: list[tuple[str, datetime]] = []
    if doc.get("captured_utc"):
        stamps.append(("captured_utc", parse_utc(doc["captured_utc"], field="captured_utc")))
    clock = doc["clock"]
    if clock.get("start_utc"):
        stamps.append(("clock.start_utc", parse_utc(clock["start_utc"], field="clock.start_utc")))
    if clock.get("end_utc"):
        stamps.append(("clock.end_utc", parse_utc(clock["end_utc"], field="clock.end_utc")))
    for index, row in enumerate(doc["summary_rows"]):
        stamps.append((f"summary_rows[{index}].utc", parse_utc(row["utc"], field="summary")))
    for index, gap in enumerate(doc["supervision"]["coverage_gaps"]):
        _seconds, stamp = _normalized_gap(gap, index)
        stamps.append((f"coverage_gaps[{index}]", stamp))
    wall = doc.get("wall") if isinstance(doc.get("wall"), dict) else {}
    invocations = _parse_invocation_list(wall)
    if invocations:
        for index, item in enumerate(invocations):
            stamps.append((f"wall.invocations[{index}].start_utc", item["start"]))
            if item["end"] is not None:
                stamps.append((f"wall.invocations[{index}].end_utc", item["end"]))
    starts = _parse_start_list(wall)
    if starts:
        for index, stamp in enumerate(starts):
            stamps.append((f"wall.starts[{index}]", stamp))
    for field, stamp in stamps:
        if _in_incident_window(stamp):
            raise CaptureError(
                f"{field} falls in the 2026-11-03..06 L2-4 window. "
                "Scaffold fixtures must be dated far from that incident."
            )


def _receipt_present(receipt: Any) -> bool:
    if isinstance(receipt, str):
        return bool(receipt.strip())
    if isinstance(receipt, dict):
        return bool(str(receipt.get("path") or "").strip())
    return False


def _parse_component_list(value: Any, field: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise CaptureError(f"{field} must be a non-empty list of numbers")
    parsed: list[float] = []
    for index, item in enumerate(value):
        raw = item
        if isinstance(item, dict):
            raw = item.get("wall_elapsed_s", item.get("elapsed_seconds", item.get("seconds")))
        if not _is_number(raw) or float(raw) < 0:
            raise CaptureError(f"{field}[{index}] must be a non-negative number")
        parsed.append(round(float(raw), 3))
    return parsed


def claimed_additive_components(wall: dict[str, Any]) -> list[float] | None:
    """Return ended-wall parts when a wall claims to be their sum. Else None.

    A single monotonic elapsed_seconds is not a sum. 259200 on one live soak
    stays a continuous wall. Two or more listed parts, an additive source, or
    an N-times-24h count is a sum and does not count toward the gate.
    """
    if not isinstance(wall, dict):
        return None
    source = str(wall.get("source") or "").strip().lower()
    flagged = source in ADDITIVE_WALL_SOURCES or any(wall.get(flag) is True for flag in ADDITIVE_FLAGS)
    count_claim = False
    for key in ADDITIVE_COUNT_KEYS:
        if key not in wall or wall.get(key) is None:
            continue
        count_claim = True
        if not _is_int(wall[key]) or wall[key] < 2:
            raise CaptureError(f"wall.{key} must be an int >= 2 when set")
    found: list[float] | None = None
    for key in ADDITIVE_LIST_KEYS:
        if key not in wall or wall.get(key) is None:
            continue
        found = _parse_component_list(wall[key], field=f"wall.{key}")
        break
    if flagged or count_claim:
        if found is not None:
            return found
        for key in ADDITIVE_COUNT_KEYS:
            if _is_int(wall.get(key)) and wall[key] >= 2:
                return [SHORT_DAY_SECONDS] * int(wall[key])
        return []
    if found is not None and len(found) >= 2:
        return found
    return None


def assess_short_sum(components: list[float]) -> dict[str, Any]:
    """Sum ended SHORT walls in memory. The sum never counts toward 259200.

    72h is one continuous monotonic wall_elapsed_s on a single live soak.
    A naive sum may land on 259200 (86400 * 3) and still does not count.
    """
    if isinstance(components, tuple):
        components = list(components)
    rounded = _parse_component_list(components, field="short_sum")
    total = round(sum(rounded), 3)
    return {
        "components_seconds": rounded,
        "component_count": len(rounded),
        "sum_seconds": total,
        "wall_required_seconds": WALL_REQUIRED_SECONDS,
        "naive_sum_reaches_259200": total >= WALL_REQUIRED_SECONDS,
        "counts_toward_gate": False,
        "historical_shorts_are_additive": False,
        "continuous_monotonic_wall": False,
        "single_live_soak": False,
    }


def standing_non_additivity(components: list[float] | None) -> dict[str, Any]:
    """Standing rule copied onto every score report. Sums do not count."""
    base: dict[str, Any] = {
        "rule": "one_continuous_monotonic_wall",
        "historical_shorts_are_additive": False,
        "sum_of_shorts_counts_toward_gate": False,
        "additive_claim": False,
        "claimed_component_count": 0,
        "claimed_sum_seconds": None,
        "naive_sum_reaches_259200": False,
        "counts_toward_gate": False,
    }
    if components is None:
        return base
    base["additive_claim"] = True
    if not components:
        return base
    assessed = assess_short_sum(components)
    base["claimed_component_count"] = assessed["component_count"]
    base["claimed_sum_seconds"] = assessed["sum_seconds"]
    base["naive_sum_reaches_259200"] = assessed["naive_sum_reaches_259200"]
    base["counts_toward_gate"] = False
    base["historical_shorts_are_additive"] = False
    base["sum_of_shorts_counts_toward_gate"] = False
    return base


def _first_wall_value(wall: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, Any] | None:
    for key in keys:
        if key not in wall or wall.get(key) is None:
            continue
        return key, wall[key]
    return None


def _invocation_pid(item: dict[str, Any], field: str) -> int | None:
    has_pid = "pid" in item and item.get("pid") is not None
    has_process = "process_id" in item and item.get("process_id") is not None
    if not has_pid and not has_process:
        return None
    pid = item.get("pid")
    process_id = item.get("process_id")
    if has_pid and (not _is_int(pid) or pid < 0):
        raise CaptureError(f"{field}.pid must be a non-negative int")
    if has_process and (not _is_int(process_id) or process_id < 0):
        raise CaptureError(f"{field}.process_id must be a non-negative int")
    if has_pid and has_process and pid != process_id:
        raise CaptureError(f"{field}.pid and process_id disagree")
    return int(pid if has_pid else process_id)


def _parse_invocation_list(wall: dict[str, Any]) -> list[dict[str, Any]] | None:
    found = _first_wall_value(wall, STITCH_LIST_KEYS)
    if found is None:
        return None
    field_name, raw = found
    field = f"wall.{field_name}"
    if not isinstance(raw, list) or not raw:
        raise CaptureError(f"{field} must be a non-empty list when set")
    parsed: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CaptureError(f"{field}[{index}] must be an object")
        start = parse_utc(item.get("start_utc"), field=f"{field}[{index}].start_utc")
        end = None
        if item.get("end_utc") is not None:
            end = parse_utc(item.get("end_utc"), field=f"{field}[{index}].end_utc")
            if end <= start:
                raise CaptureError(f"{field}[{index}].end_utc must be after start_utc")
        elapsed = item.get("wall_elapsed_s", item.get("elapsed_seconds"))
        if not _is_number(elapsed) or float(elapsed) < 0:
            raise CaptureError(f"{field}[{index}].wall_elapsed_s must be a non-negative number")
        host = item.get("host")
        if host is not None and (not isinstance(host, str) or not host.strip()):
            raise CaptureError(f"{field}[{index}].host must be a non-empty string or null")
        parsed.append(
            {
                "start": start,
                "end": end,
                "pid": _invocation_pid(item, f"{field}[{index}]"),
                "wall_elapsed_s": round(float(elapsed), 3),
                "host": host.strip() if isinstance(host, str) else None,
            }
        )
    return parsed


def _parse_wall_samples(wall: dict[str, Any]) -> list[float] | None:
    found = _first_wall_value(wall, WALL_SERIES_KEYS)
    if found is None:
        return None
    field_name, raw = found
    field = f"wall.{field_name}"
    if not isinstance(raw, list) or not raw:
        raise CaptureError(f"{field} must be a non-empty list of numbers")
    parsed: list[float] = []
    for index, item in enumerate(raw):
        if not _is_number(item) or float(item) < 0:
            raise CaptureError(f"{field}[{index}] must be a non-negative number")
        parsed.append(round(float(item), 3))
    return parsed


def _parse_start_list(wall: dict[str, Any]) -> list[datetime] | None:
    found = _first_wall_value(wall, START_LIST_KEYS)
    if found is None:
        return None
    field_name, raw = found
    field = f"wall.{field_name}"
    if not isinstance(raw, list) or not raw:
        raise CaptureError(f"{field} must be a non-empty list of timestamps")
    return [parse_utc(item, field=f"{field}[{index}]") for index, item in enumerate(raw)]


def _parse_pid_list(wall: dict[str, Any]) -> list[int] | None:
    found = _first_wall_value(wall, PID_LIST_KEYS)
    if found is None:
        return None
    field_name, raw = found
    field = f"wall.{field_name}"
    if not isinstance(raw, list) or not raw:
        raise CaptureError(f"{field} must be a non-empty list of process ids")
    parsed: list[int] = []
    for index, item in enumerate(raw):
        if not _is_int(item) or item < 0:
            raise CaptureError(f"{field}[{index}] must be a non-negative int")
        parsed.append(int(item))
    return parsed


def _segment_peaks(samples: list[float]) -> tuple[list[float], bool]:
    """Split a wall series where it resets or goes backwards.

    Each monotonic run contributes its last sample. A later sample that is
    lower than the previous sample is a new run, not a continuation.
    """
    if not samples:
        return [], False
    peaks: list[float] = []
    previous = samples[0]
    peak = samples[0]
    reset = False
    for value in samples[1:]:
        if value < previous:
            peaks.append(peak)
            peak = value
            reset = True
        else:
            peak = value
        previous = value
    peaks.append(peak)
    return peaks, reset


def _coerce_starts(values: list[Any] | None) -> list[datetime]:
    if not values:
        return []
    parsed: list[datetime] = []
    for index, value in enumerate(values):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise CaptureError(f"starts[{index}] must include a UTC offset")
            parsed.append(value.astimezone(timezone.utc))
        else:
            parsed.append(parse_utc(value, field=f"starts[{index}]"))
    return parsed


def _coerce_pids(values: list[Any] | None) -> list[int]:
    if not values:
        return []
    parsed: list[int] = []
    for index, value in enumerate(values):
        if not _is_int(value) or value < 0:
            raise CaptureError(f"pids[{index}] must be a non-negative int")
        parsed.append(int(value))
    return parsed


def synthetic_sequential_soaks(
    walls: list[float],
    *,
    pid_base: int = 7100,
    host: str = "synthetic-host",
) -> list[dict[str, Any]]:
    """In-memory ended soaks placed back-to-back. Not a file and not a live process."""
    if not isinstance(walls, list) or not walls:
        raise CaptureError("sequential soaks need a non-empty list of wall seconds")
    cursor = STITCH_ANCHOR
    rows: list[dict[str, Any]] = []
    for index, wall in enumerate(walls):
        if not _is_number(wall) or float(wall) < 0:
            raise CaptureError(f"sequential soaks[{index}] must be a non-negative number")
        seconds = round(float(wall), 3)
        end = cursor + timedelta(seconds=seconds)
        rows.append(
            {
                "start_utc": utc_z(cursor),
                "end_utc": utc_z(end),
                "pid": pid_base + index,
                "wall_elapsed_s": seconds,
                "host": host,
            }
        )
        cursor = end
    return rows


def assess_process_continuity(
    invocations: list[dict[str, Any]] | None = None,
    wall_samples: list[float] | None = None,
    extra_starts: list[Any] | None = None,
    extra_pids: list[Any] | None = None,
) -> dict[str, Any]:
    """Score sequential or restarted soaks. The stitch never counts toward 259200.

    72h is one continuous monotonic wall_elapsed_s on a single live soak
    process. A back-to-back pair, a 72h calendar of three 86400 soaks, or a
    wall that resets may show a stitched duration of 259200 and still does
    not count. Same host does not make them one process.
    """
    if invocations is None:
        invocations = []
    if not isinstance(invocations, list):
        raise CaptureError("invocations must be a list")
    normalized = _parse_invocation_list({"invocations": invocations}) if invocations else []
    samples = _parse_wall_samples({"wall_samples": wall_samples}) if wall_samples is not None else None
    peaks, wall_reset = _segment_peaks(samples or [])
    starts = [item["start"] for item in normalized]
    starts.extend(_coerce_starts(extra_starts))
    pids = [item["pid"] for item in normalized if item["pid"] is not None]
    pids.extend(_coerce_pids(extra_pids))
    if normalized:
        duration: float | None = round(sum(item["wall_elapsed_s"] for item in normalized), 3)
        segment_count = len(normalized)
    elif samples:
        duration = round(sum(peaks), 3)
        segment_count = len(peaks)
    else:
        duration = None
        segment_count = 0
    if normalized:
        earliest = min(item["start"] for item in normalized)
        latest = max(item["end"] or item["start"] for item in normalized)
        span: float | None = round((latest - earliest).total_seconds(), 3)
    else:
        span = None
    back_to_back = False
    if len(normalized) >= 2 and all(item["end"] is not None for item in normalized):
        back_to_back = all(
            normalized[index]["start"] == normalized[index - 1]["end"] for index in range(1, len(normalized))
        )
    hosts = [item["host"] for item in normalized]
    same_host = bool(hosts) and all(isinstance(host, str) and host for host in hosts) and len(set(hosts)) == 1
    distinct_starts = len({utc_z(item) for item in starts})
    distinct_pids = len(set(pids))
    single = (
        len(normalized) == 1
        and not wall_reset
        and distinct_starts <= 1
        and distinct_pids <= 1
        and segment_count <= 1
    )
    return {
        "invocation_count": len(normalized),
        "distinct_start_count": distinct_starts,
        "distinct_process_count": distinct_pids,
        "segment_count": segment_count,
        "same_host": same_host,
        "wall_reset": wall_reset,
        "back_to_back": back_to_back,
        "walls_seconds": [item["wall_elapsed_s"] for item in normalized],
        "wall_samples": samples,
        "stitched_duration_seconds": duration,
        "calendar_span_seconds": span,
        "wall_required_seconds": WALL_REQUIRED_SECONDS,
        "stitched_duration_reaches_259200": duration is not None and duration >= WALL_REQUIRED_SECONDS,
        "calendar_span_reaches_259200": span is not None and span >= WALL_REQUIRED_SECONDS,
        "counts_toward_gate": False,
        "sequential_soaks_are_continuous": False,
        "stitched_processes_count_toward_gate": False,
        "single_live_process": single,
    }


def claimed_process_boundary(wall: dict[str, Any]) -> dict[str, Any] | None:
    """Return a stitch claim when a wall joins two or more soak processes.

    A single monotonic elapsed_seconds is not a stitch. 259200 on one live
    soak stays a continuous wall. Two or more invocations, different start
    timestamps, different process ids, a wall that resets, or an explicit
    stitch source does not count toward the gate.
    """
    if not isinstance(wall, dict):
        return None
    source = str(wall.get("source") or "").strip().lower()
    explicit = source in STITCH_WALL_SOURCES or any(wall.get(flag) is True for flag in STITCH_FLAGS)
    invocations = _parse_invocation_list(wall)
    samples = _parse_wall_samples(wall)
    starts = _parse_start_list(wall)
    pids = _parse_pid_list(wall)
    _peaks, reset = _segment_peaks(samples or [])
    multi = invocations is not None and len(invocations) >= 2
    multi_starts = starts is not None and len({utc_z(item) for item in starts}) >= 2
    multi_pids = pids is not None and len(set(pids)) >= 2
    invocation_starts = 0
    invocation_pids = 0
    if invocations:
        invocation_starts = len({utc_z(item["start"]) for item in invocations})
        invocation_pids = len({item["pid"] for item in invocations if item["pid"] is not None})
    if not any((explicit, reset, multi, multi_starts, multi_pids, invocation_starts >= 2, invocation_pids >= 2)):
        return None
    raw_invocations: list[Any] = []
    found = _first_wall_value(wall, STITCH_LIST_KEYS)
    if found is not None and isinstance(found[1], list):
        raw_invocations = list(found[1])
    return {
        "invocations": raw_invocations,
        "wall_samples": samples,
        "starts": [utc_z(item) for item in (starts or [])],
        "pids": list(pids or []),
    }


def standing_process_continuity(
    claim: dict[str, Any] | None,
    *,
    claimed_elapsed: float | None = None,
) -> dict[str, Any]:
    """Standing rule copied onto every score report. Stitches do not count."""
    base: dict[str, Any] = {
        "rule": "one_live_soak_process",
        "sequential_soaks_are_continuous": False,
        "stitched_processes_count_toward_gate": False,
        "stitch_claim": False,
        "claimed_invocation_count": 0,
        "distinct_start_count": 0,
        "distinct_process_count": 0,
        "segment_count": 0,
        "wall_reset": False,
        "same_host": False,
        "back_to_back": False,
        "stitched_duration_seconds": None,
        "calendar_span_seconds": None,
        "stitched_duration_reaches_259200": False,
        "calendar_span_reaches_259200": False,
        "counts_toward_gate": False,
    }
    if claim is None:
        return base
    assessed = assess_process_continuity(
        list(claim.get("invocations") or []),
        wall_samples=claim.get("wall_samples"),
        extra_starts=list(claim.get("starts") or []),
        extra_pids=list(claim.get("pids") or []),
    )
    duration = assessed["stitched_duration_seconds"]
    if duration is None and _is_number(claimed_elapsed):
        duration = round(float(claimed_elapsed), 3)
    base["stitch_claim"] = True
    base["claimed_invocation_count"] = assessed["invocation_count"]
    base["distinct_start_count"] = assessed["distinct_start_count"]
    base["distinct_process_count"] = assessed["distinct_process_count"]
    base["segment_count"] = assessed["segment_count"]
    base["wall_reset"] = assessed["wall_reset"]
    base["same_host"] = assessed["same_host"]
    base["back_to_back"] = assessed["back_to_back"]
    base["stitched_duration_seconds"] = duration
    base["calendar_span_seconds"] = assessed["calendar_span_seconds"]
    base["stitched_duration_reaches_259200"] = duration is not None and duration >= WALL_REQUIRED_SECONDS
    base["calendar_span_reaches_259200"] = assessed["calendar_span_reaches_259200"]
    base["sequential_soaks_are_continuous"] = False
    base["stitched_processes_count_toward_gate"] = False
    base["counts_toward_gate"] = False
    return base


def _forged_claim(doc: dict[str, Any]) -> bool:
    status = str(doc.get("claimed_l2_2_status") or "").strip().upper().replace(" ", "_")
    production = str(doc.get("claimed_production_7x24") or "").strip().upper().replace(" ", "_")
    if status in {"PASS", "ACCEPTED"} or status.startswith("PASS"):
        return True
    if production in {"", "NOT_ACCEPTED", "NOT_STARTED", "INCOMPLETE", "UNSCORED"}:
        return False
    return production in {"ACCEPTED", "PASS", "PRODUCTION_ACCEPTED"} or "ACCEPTED" in production


def _classify_gap(seconds: float) -> str:
    return gaplog.classify_band(seconds, yellow_min=YELLOW_MIN_SECONDS, red_min=RED_MIN_SECONDS)


def _normalized_gap(gap: dict[str, Any], index: int) -> tuple[float, datetime]:
    """Accept logger fields (gap_seconds, timestamp, band) or seconds/utc."""
    has_seconds = "seconds" in gap and gap["seconds"] is not None
    has_gap = "gap_seconds" in gap and gap["gap_seconds"] is not None
    if has_seconds and not _is_number(gap["seconds"]):
        raise CaptureError(f"coverage_gaps[{index}].seconds must be a number")
    if has_gap and not _is_number(gap["gap_seconds"]):
        raise CaptureError(f"coverage_gaps[{index}].gap_seconds must be a number")
    if has_seconds and has_gap and float(gap["seconds"]) != float(gap["gap_seconds"]):
        raise CaptureError(f"coverage_gaps[{index}] seconds and gap_seconds disagree")
    if not has_seconds and not has_gap:
        raise CaptureError(f"coverage_gaps[{index}] needs seconds or gap_seconds")
    seconds = float(gap["seconds"] if has_seconds else gap["gap_seconds"])
    if seconds < 0:
        raise CaptureError(f"coverage_gaps[{index}] gap must be >= 0")
    has_utc = "utc" in gap and gap["utc"] is not None
    has_timestamp = "timestamp" in gap and gap["timestamp"] is not None
    if not has_utc and not has_timestamp:
        raise CaptureError(f"coverage_gaps[{index}] needs utc or timestamp")
    stamp = parse_utc(
        gap["utc"] if has_utc else gap["timestamp"],
        field=f"coverage_gaps[{index}].timestamp",
    )
    if has_utc and has_timestamp:
        other = parse_utc(gap["timestamp"], field=f"coverage_gaps[{index}].timestamp")
        if other != stamp:
            raise CaptureError(f"coverage_gaps[{index}] utc and timestamp disagree")
    band = gap.get("band")
    if band is not None:
        if band not in gaplog.BANDS:
            raise CaptureError(f"coverage_gaps[{index}].band must be ok, yellow, or red")
        expected = _classify_gap(seconds)
        if band != expected:
            raise CaptureError(
                f"coverage_gaps[{index}].band {band} does not match the gap ({expected})"
            )
    return seconds, stamp


def _reconcile(metrics: dict[str, Any] | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if metrics is None:
        return {"status": "not_applicable", "mismatches": []}
    if not rows:
        return {"status": "missing", "mismatches": ["summary_rows"]}
    exit0 = sum(1 for row in rows if row.get("exit") == 0)
    work = sum(1 for row in rows if row.get("with_work") is True)
    idle = sum(1 for row in rows if row.get("idle") is True)
    expected = {
        "cycles_ran": len(rows),
        "cycles_exit0": exit0,
        "cycles_with_work": work,
        "cycles_idle": idle,
    }
    mismatches = [key for key, value in expected.items() if metrics.get(key) != value]
    return {"status": "match" if not mismatches else "mismatch", "mismatches": mismatches}


def _runner_allowed(runner: dict[str, Any]) -> bool:
    return (
        runner.get("kind") in ALLOWED_RUNNER_KINDS
        and runner.get("interactive") is False
        and runner.get("registered_this_run") is False
        and runner.get("task_names") == []
    )


def _runner_forbidden(runner: dict[str, Any]) -> bool:
    return (
        runner.get("kind") in FORBIDDEN_RUNNER_KINDS
        or runner.get("interactive") is True
        or runner.get("registered_this_run") is True
        or bool(runner.get("task_names"))
    )


def score(doc: dict[str, Any]) -> dict[str, Any]:
    validate_capture(doc)
    started = doc["clock"]["started"] is True
    evidence = doc["evidence_class"]
    wall = doc["wall"]
    metrics = doc["metrics"]
    runner = doc["runner"]
    supervision = doc["supervision"]
    rows = doc["summary_rows"]
    source = wall["source"]
    elapsed = wall["elapsed_seconds"]
    reconciliation = _reconcile(metrics, rows)
    runner_ok = started and _runner_allowed(runner)
    runner_bad = _runner_forbidden(runner)
    r2 = supervision["r2_declared_before_start"] is True
    r3 = _receipt_present(supervision.get("r3_injection_receipt"))
    watch = supervision.get("watch_target")
    expected_watch = WATCH_FOR_KIND.get(str(runner.get("kind")))
    watch_live = started and watch is not None and watch == expected_watch
    ended_watch = isinstance(watch, str) and watch in ENDED_WATCH_TARGETS

    gaps = []
    red_gaps = 0
    yellow_gaps = 0
    for index, gap in enumerate(supervision["coverage_gaps"]):
        seconds, stamp = _normalized_gap(gap, index)
        kind = _classify_gap(seconds)
        if kind == "red":
            red_gaps += 1
        elif kind == "yellow":
            yellow_gaps += 1
        gaps.append(
            {
                "utc": utc_z(stamp),
                "seconds": seconds,
                "class": kind,
            }
        )

    elapsed_meets = _is_number(elapsed) and float(elapsed) >= WALL_REQUIRED_SECONDS
    additive_components = claimed_additive_components(wall)
    additive_claim = additive_components is not None
    non_additivity = standing_non_additivity(additive_components)
    boundary = claimed_process_boundary(wall)
    stitch_claim = boundary is not None
    continuity = standing_process_continuity(
        boundary,
        claimed_elapsed=float(elapsed) if stitch_claim and _is_number(elapsed) else None,
    )
    metrics_wall_agrees = False
    if isinstance(metrics, dict) and _is_number(elapsed):
        metrics_wall_agrees = abs(float(metrics["wall_elapsed_s"]) - float(elapsed)) <= WALL_MATCH_TOLERANCE
        metrics_wall_agrees = metrics_wall_agrees and metrics.get("max_wall_seconds") == wall.get("max_wall_seconds")
    final_stop = (
        isinstance(metrics, dict)
        and metrics.get("final") is True
        and metrics.get("stopped_early") == "max_wall_seconds"
        and wall.get("max_wall_seconds") == WALL_REQUIRED_SECONDS
    )
    monotonic = source == "monotonic"
    wall_bar = bool(
        runner_ok
        and monotonic
        and elapsed_meets
        and metrics_wall_agrees
        and final_stop
        and not additive_claim
        and not stitch_claim
    )
    with_work = isinstance(metrics, dict) and metrics.get("cycles_with_work", 0) > 0
    summary_ok = reconciliation["status"] == "match"
    git_sha_present = isinstance(doc.get("git_sha"), str) and bool(doc["git_sha"].strip())
    bars = {
        "host_evidence": evidence == "host_observation",
        "clock_started": started,
        "runner_non_interactive": runner_ok,
        "wall_monotonic_72h": wall_bar,
        "with_work": with_work,
        "summary_reconciled": summary_ok,
        "r2_declared_before_start": started and r2,
        "r3_receipt_present": started and r3,
        "watch_target_live": watch_live,
        "git_sha_present": git_sha_present,
    }

    if not started:
        clock_state = "NOT_STARTED"
        status = "NOT_STARTED"
    else:
        status = "INCOMPLETE"
        if additive_claim or stitch_claim or not monotonic or elapsed is None:
            clock_state = "INCOMPLETE"
        elif elapsed_meets:
            clock_state = "WALL_OBSERVED"
        else:
            clock_state = "SHORT"

    blockers = list(PERMANENT_BLOCKERS)
    if evidence == "scaffold":
        blockers.append("scaffold_fixture_not_host_evidence")
    if not started:
        blockers.append("clock_not_started")
    if runner_bad:
        blockers.append("interactive_registration_forbidden")
    elif started and not runner_ok:
        blockers.append("runner_not_allowed")
    if additive_claim:
        blockers.append("additive_historical_shorts")
    if stitch_claim:
        blockers.append("stitched_process_boundaries")
    if started and not monotonic:
        blockers.append("wall_not_monotonic")
    if started and not elapsed_meets:
        blockers.append("wall_short")
    if started and wall.get("max_wall_seconds") != WALL_REQUIRED_SECONDS:
        blockers.append("max_wall_seconds_not_72h")
    if started and isinstance(metrics, dict) and not metrics_wall_agrees:
        blockers.append("wall_elapsed_disagrees_with_metrics")
    if started and isinstance(metrics, dict) and metrics.get("final") is not True:
        blockers.append("metrics_not_final")
    if started and isinstance(metrics, dict) and metrics.get("stopped_early") != "max_wall_seconds":
        blockers.append("stopped_early_not_max_wall")
    if started and not with_work:
        blockers.append("exit0_is_not_business")
    if started and reconciliation["status"] == "missing":
        blockers.append("summary_rows_missing")
    if started and reconciliation["status"] == "mismatch":
        blockers.append("metrics_summary_mismatch")
    if started and not r2:
        blockers.append("r2_not_declared_before_start")
    if started and not r3:
        blockers.append("r3_receipt_absent")
    if ended_watch:
        blockers.append("ended_experiment_watch_forbidden")
    elif started and not watch_live and not runner_bad:
        blockers.append("watch_target_not_live")
    if red_gaps:
        blockers.append("red_coverage_gap")
    if started and not git_sha_present:
        blockers.append("git_sha_missing")
    if _forged_claim(doc):
        blockers.append("forged_claim_ignored")

    stopped = metrics.get("stopped_early") if isinstance(metrics, dict) else None
    supervision_fault = bool(ended_watch or red_gaps or (started and not r2))
    if started and not watch_live and not runner_bad and not ended_watch:
        supervision_fault = True
    triage = {
        "business": False,
        "host": isinstance(stopped, str) and stopped in HOST_STOPS,
        "supervision": supervision_fault,
        "policy": runner_bad,
    }

    report = {
        "schema": SCHEMA_REPORT,
        "evidence_class": evidence,
        "label": "scaffold" if evidence == "scaffold" else "host_observation_unverified",
        "verified": False,
        "supervision_verified": False,
        "l2_2_status": status,
        "clock_state": clock_state,
        "production_7x24": "NOT_ACCEPTED",
        "business_verdict": "UNSCORED",
        "business_fail": False,
        "product_l2_task_split": "NOT_STARTED",
        "interactive_registration": "founder_gated_out_of_scope",
        "definition": {
            "wall_required_seconds": WALL_REQUIRED_SECONDS,
            "wall_source_required": "monotonic",
            "driver": "scripts/soak_2h.py --via-l1 --max-wall-seconds 259200",
            "exit0_is_business": False,
            "interactive_schtasks": "out_of_scope",
            "note": (
                "72h means one continuous monotonic wall_elapsed_s >= 259200 "
                "with max_wall_seconds 259200 on a single live soak process. "
                "A sum of ended SHORT walls is not that wall. "
                "Stitching sequential or restarted invocations is not that wall, "
                "even when the stitched duration or calendar span reaches 259200. "
                "A wall that resets or goes backwards is not that wall. "
                "cycles x interval is not the wall. cycles_exit0 is process success only."
            ),
        },
        "bars": bars,
        "bars_all_true": all(bars.values()),
        "wall": {
            "required_seconds": WALL_REQUIRED_SECONDS,
            "elapsed_seconds": elapsed,
            "source": source,
            "elapsed_meets_259200": False if additive_claim or stitch_claim else elapsed_meets,
            "counts_toward_gate": wall_bar,
            "additive_claim": additive_claim,
            "stitch_claim": stitch_claim,
        },
        "non_additivity": non_additivity,
        "process_continuity": continuity,
        "reconciliation": reconciliation,
        "coverage_gaps": {
            "yellow": yellow_gaps,
            "red": red_gaps,
            "rows": gaps,
            "yellow_is_not_business_fail": True,
        },
        "runner": {
            "kind": runner.get("kind"),
            "allowed": runner_ok,
            "rejected": runner_bad,
            "registered_this_run": runner.get("registered_this_run"),
            "interactive": runner.get("interactive"),
            "task_names": list(runner.get("task_names") or []),
        },
        "triage": triage,
        "gates": {
            "can_accept_l2_2": False,
            "can_close_l2_2": False,
            "can_start_clock": False,
            "close_policy": (
                "This tool never accepts L2-2 and never starts the 72h clock. "
                "A later explicit non-Interactive run can be reviewed by the observation track. "
                "Production 7x24 stays NOT ACCEPTED. Interactive console scheduled tasks stay out of scope."
            ),
            "blockers": blockers,
        },
        "l2_4": dict(L2_4_CROSSLINK),
        "next_steps": list(NEXT_STEPS),
        "source": {
            "synthetic": doc.get("synthetic") is True,
            "note": doc.get("note"),
            "host": doc.get("host"),
            "git_sha": doc.get("git_sha"),
            "captured_utc": doc.get("captured_utc"),
            "collector": "scripts/l2_2_score.py",
            "collector_mode": "offline_score",
        },
    }
    violations = validate_report(report)
    if violations:
        raise CaptureError("refusing to emit report: " + ",".join(violations))
    return report


def _non_additivity_violations(report: dict[str, Any]) -> list[str]:
    """Reject a report that adds ended SHORT walls toward 259200 or relabels the sum."""
    violations: list[str] = []
    block = report.get("non_additivity")
    wall = report.get("wall") if isinstance(report.get("wall"), dict) else {}
    if not isinstance(block, dict):
        return ["non_additivity"]
    if block.get("rule") != "one_continuous_monotonic_wall":
        violations.append("non_additivity")
    if block.get("historical_shorts_are_additive") is not False:
        violations.append("additive_historical_shorts")
    if block.get("sum_of_shorts_counts_toward_gate") is not False:
        violations.append("additive_historical_shorts")
    if block.get("counts_toward_gate") is not False:
        violations.append("additive_historical_shorts")
    if not isinstance(block.get("additive_claim"), bool):
        violations.append("non_additivity")
    try:
        claimed = claimed_additive_components(wall)
    except CaptureError:
        violations.append("additive_historical_shorts")
        claimed = None
    if claimed is not None and block.get("additive_claim") is not True:
        violations.append("additive_historical_shorts")
    if claimed is not None and wall.get("counts_toward_gate") is not False:
        violations.append("additive_historical_shorts")
    if block.get("additive_claim") is True:
        if wall.get("counts_toward_gate") is not False:
            violations.append("additive_historical_shorts")
        if report.get("clock_state") == "WALL_OBSERVED":
            violations.append("additive_historical_shorts")
        if report.get("l2_2_status") == "PASS":
            violations.append("forged_pass")
        if report.get("production_7x24") != "NOT_ACCEPTED":
            violations.append("production_claim")
    return violations


def _process_continuity_violations(report: dict[str, Any]) -> list[str]:
    """Reject a report that stitches soak processes and relabels the stitch as 72h."""
    violations: list[str] = []
    block = report.get("process_continuity")
    wall = report.get("wall") if isinstance(report.get("wall"), dict) else {}
    if not isinstance(block, dict):
        return ["process_continuity"]
    if block.get("rule") != "one_live_soak_process":
        violations.append("process_continuity")
    if block.get("sequential_soaks_are_continuous") is not False:
        violations.append("stitched_process_boundaries")
    if block.get("stitched_processes_count_toward_gate") is not False:
        violations.append("stitched_process_boundaries")
    if block.get("counts_toward_gate") is not False:
        violations.append("stitched_process_boundaries")
    if not isinstance(block.get("stitch_claim"), bool):
        violations.append("process_continuity")
    try:
        claimed = claimed_process_boundary(wall)
    except CaptureError:
        violations.append("stitched_process_boundaries")
        claimed = None
    if claimed is not None and block.get("stitch_claim") is not True:
        violations.append("stitched_process_boundaries")
    if claimed is not None and wall.get("counts_toward_gate") is not False:
        violations.append("stitched_process_boundaries")
    if block.get("stitch_claim") is True:
        if wall.get("counts_toward_gate") is not False:
            violations.append("stitched_process_boundaries")
        if wall.get("stitch_claim") is not True:
            violations.append("stitched_process_boundaries")
        if report.get("clock_state") == "WALL_OBSERVED":
            violations.append("stitched_process_boundaries")
        if report.get("l2_2_status") == "PASS":
            violations.append("forged_pass")
        if report.get("production_7x24") != "NOT_ACCEPTED":
            violations.append("production_claim")
    elif wall.get("stitch_claim") is True:
        violations.append("stitched_process_boundaries")
    return violations


def validate_report(report: dict[str, Any]) -> list[str]:
    """Reject forged acceptance. Empty list means the report does not over-claim."""
    violations: list[str] = []
    if report.get("schema") != SCHEMA_REPORT:
        violations.append("schema")
    if report.get("production_7x24") != "NOT_ACCEPTED":
        violations.append("production_claim")
    if report.get("l2_2_status") == "PASS":
        violations.append("forged_pass")
    if report.get("l2_2_status") not in {"NOT_STARTED", "INCOMPLETE"}:
        violations.append("status")
    if report.get("verified") is not False:
        violations.append("verified_claim")
    if report.get("supervision_verified") is not False:
        violations.append("supervision_verified_claim")
    if report.get("business_fail") is not False:
        violations.append("business_fail_not_supported")
    if report.get("business_verdict") != "UNSCORED":
        violations.append("business_verdict")
    if report.get("product_l2_task_split") != "NOT_STARTED":
        violations.append("product_l2_claim")
    if report.get("interactive_registration") != "founder_gated_out_of_scope":
        violations.append("interactive_registration")
    if report.get("evidence_class") not in {"scaffold", "host_observation"}:
        violations.append("evidence_class")
    gates = report.get("gates") if isinstance(report.get("gates"), dict) else {}
    if gates.get("can_accept_l2_2") is not False:
        violations.append("forged_accept")
    if gates.get("can_close_l2_2") is not False:
        violations.append("forged_close")
    if gates.get("can_start_clock") is not False:
        violations.append("forged_clock_start")
    if report.get("evidence_class") == "scaffold" and gates.get("can_accept_l2_2") is True:
        violations.append("scaffold_cannot_accept")
    violations.extend(_non_additivity_violations(report))
    violations.extend(_process_continuity_violations(report))
    label = report.get("label")
    if report.get("evidence_class") == "scaffold" and label != "scaffold":
        violations.append("label")
    if report.get("evidence_class") == "host_observation" and label != "host_observation_unverified":
        violations.append("label")
    l2_4 = report.get("l2_4") if isinstance(report.get("l2_4"), dict) else {}
    if l2_4.get("status") != "INCOMPLETE" or l2_4.get("relitigated") is not False:
        violations.append("l2_4_crosslink")
    steps = report.get("next_steps")
    if not isinstance(steps, list) or not steps:
        violations.append("next_steps")
    return violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        doc = load_capture(args.capture)
        report = score(doc)
    except CaptureError as exc:
        print(json.dumps({"ok": False, "error": "invalid_capture", "detail": str(exc)}))
        return 2
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(text, end="")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
