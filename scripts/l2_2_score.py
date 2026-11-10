#!/usr/bin/env python3
"""Offline scorer for the Grok duty-cycle L2-2 72h wall soak.

Reads a capture bundle (schema aistudioos-grok.l2-2.capture.v1) and writes an
honest report. This tool does not start a clock, does not register scheduled
tasks, and never emits L2-2 PASS or production 7x24 acceptance. A sum of ended
SHORT walls does not count. Stitching sequential or restarted soak invocations
into one capture does not count, even when the stitched span reaches 259200.
The Issue #9 conditional founder approval is not a start. A report cannot
pretend the five start conditions are satisfied, pretend that approval started
the clock, treat LOCAL_ONLY as public evidence, end on an unknown root cause,
or treat the soak-DUT stall watchdog as a watchdog of the supervisor.
An offline synthetic supervisor probe is not that watchdog either, does not
satisfy founder condition 2, and is not a start.

Exit 0: an honest NOT_STARTED or INCOMPLETE report was produced.
Exit 2: the capture or the report failed validation.

  python3 scripts/l2_2_score.py --capture tests/fixtures/l2_2/scaffold_clock_not_started.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
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

# Conditional founder approval on Issue #9. Recording it is not a start.
FOUNDER_APPROVAL_ISSUE = 9
FOUNDER_APPROVAL_COMMENT_ID = 6761044915
FOUNDER_APPROVAL_UTC = "2026-11-10T06:50:14Z"
FOUNDER_APPROVAL_PR = 12
SUPERVISION_WRITE_MAX_SECONDS = 600  # at least once every 10 minutes
SUPERVISOR_WATCHDOG_MAX_SECONDS = 10
FOUNDER_CONDITION_IDS = (
    "supervision_policy",
    "supervision_cadence_and_supervisor_watchdog",
    "public_evidence",
    "three_way_attribution",
    "not_production_7x24",
)
FOUNDER_CONDITION_DETAILS = frozenset(
    {
        "not_declared",
        "satisfied",
        "band_mismatch",
        "clock_not_monotonic",
        "write_gap_too_wide",
        "supervisor_watchdog_missing",
        "soak_dut_watchdog_is_not_supervisor_watchdog",
        "crash_record_too_slow",
        "local_only_refused",
        "public_parts_missing",
        "unknown_root_cause_refused",
        "ways_incomplete",
        "production_claim_refused",
        "pass_claimed_as_readiness",
    }
)
WATCHDOG_REFUSAL_DETAILS = frozenset(
    {
        "supervisor_watchdog_missing",
        "soak_dut_watchdog_is_not_supervisor_watchdog",
        "crash_record_too_slow",
    }
)
SOAK_DUT_WATCHDOG_KINDS = frozenset(
    {
        "soak_dut",
        "soak_dut_stall_watchdog",
        "stall_watchdog",
        "soak_summary",
        "soak_summary_live",
    }
)
SUPERVISOR_WATCHDOG_KIND = "other_process"
# Offline honesty probe. Temp files only. Not a live supervisor and not a start.
SUPERVISOR_PROBE_RULE = "other_process_records_supervisor_crash_within_10s"
SUPERVISOR_PROBE_DETAIL = "synthetic_alive_vs_crash_unrecorded"
SUPERVISOR_PROBE_ACTION = "synthetic_supervisor_files"
SUPERVISOR_PROBE_DUT = "synthetic_temp_supervisor"
SUPERVISOR_PROBE_TOOL = "scripts/l2_2_score.py"
SOAK_DUT_STALL_TOOL = "scripts/stall_watchdog.py"
SUPERVISOR_PROBE_UTC = "2026-02-01T00:00:00Z"
SUPERVISOR_ALIVE_MAX_AGE_SECONDS = 1.0
SUPERVISOR_CRASH_OFFSET_SECONDS = 30.0
SUPERVISOR_SLOW_RECORD_SECONDS = 11
SUPERVISOR_PROBE_HOLE = "offline_probe_is_not_a_live_supervisor_watchdog"
SUPERVISOR_PROBE_NOTE = (
    "This offline probe classifies synthetic temp files only. "
    "It does not satisfy founder condition 2. "
    "It is not a supervisor watchdog of a live supervisor. "
    "It is not a start. "
    "scripts/stall_watchdog.py watches a soak DUT and is not this watchdog."
)
SUPERVISOR_CONDITION_2 = (
    "supervision_write_at_least_once_every_10_minutes_and_another_process_records_a_supervisor_crash_within_10s"
)
SUPERVISOR_PROBE_LABELS = (
    "supervisor_alive",
    "supervisor_crash_unrecorded",
    "supervisor_crash_record_too_slow",
)
SUPERVISOR_PROBE_DETAILS = frozenset(
    {
        SUPERVISOR_PROBE_DETAIL,
        "classification_failed",
        "probe_failed",
        "probe_in_repo",
        "probe_io",
        "scorer_import",
        "forged_supervisor_watchdog_not_refused",
    }
)
OFFLINE_PROBE_KINDS = frozenset(
    {
        "offline_synthetic_probe",
        "synthetic_probe",
        "offline_probe",
        "synthetic_supervisor_files",
        "supervisor_watchdog_probe",
    }
)
ATTRIBUTION_WAYS = frozenset({"business", "host", "supervision"})
ATTRIBUTION_TERMINALS = frozenset({"none", "business", "host", "supervision"})
UNKNOWN_ROOT_TOKENS = frozenset({"unknown", "unknown_root_cause"})
LOCAL_ONLY_TOKEN = "local_only"
# A posted start line has a 40-hex sha. The placeholder shape does not match.
START_REGISTRATION_RE = re.compile(
    r"(?m)^[ \t]*L2-2 START:[ \t]+utc=\S+[ \t]+sha=[0-9a-fA-F]{40}[ \t]+host=\S+[ \t]+max_wall_seconds=259200[ \t]*$"
)

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
    "Product L2 (self-decompose / self-implement) is CONDITIONAL on the observation track, not granted, pending one end-to-end T3: a new goal and a new schema, the product derives the task set, then executes and delivers, with no handwritten dispatch. T2 DS-T2-20261110 is ACCEPTED (Issue #9 comment 6765608469, 2026-11-10T11:00:40Z, evidence PR #13 tip 9cac002). Comment 6767990189 (2026-11-10T13:00:44Z) accepted the PR #14 tip 738b47a derivation evidence and left L2 CONDITIONAL. No task_inbox/DS-T3 card is on main. PR #15 tip a07ec9f prepared that path with a local demo fixture and is not a T3 run and not acceptance. This scorer does not run T3, does not rerun T1 or T2, and does not grant product L2. L2-3 mid-run kill recovery is a separate gate.",
    "Issue #9 comment 6761044915 (2026-11-10T06:50:14Z) is a conditional founder approval for PR #12. That approval is not a start, not a PASS, and it does not set can_start_clock. The five conditions stay unsatisfied until a later explicit declaration: supervision policy (yellow 13s through 300s, red above 300s, monotonic clock), supervision writes at least once every 10 minutes and a separate process records a supervisor crash within 10s (the soak-DUT stall watchdog is not that watchdog; an offline synthetic supervisor-alive versus supervisor-crash-unrecorded probe is not that watchdog either and does not satisfy condition 2), public evidence of final metrics plus a log summary plus a SHA list (LOCAL_ONLY does not count), three-way failure attribution (business, host, supervision; unknown root cause is not a terminal attribution), and no production 7x24 claim. A 72h result is not production readiness. This scorer does not post the L2-2 START line.",
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
    if "founder_start" in doc:
        _validate_founder_start(doc.get("founder_start"))
    if "supervisor_watchdog_claim" in doc and doc["supervisor_watchdog_claim"] is not None and not isinstance(
        doc["supervisor_watchdog_claim"], dict
    ):
        raise CaptureError("supervisor_watchdog_claim must be an object or null")

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


def _norm_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", " ").replace("_", " ")


def _token_key(value: Any) -> str:
    return "_".join(_norm_token(value).split())


def start_registration_line_present(text: str) -> bool:
    """True only for a filled L2-2 START line with a 40-hex sha.

    The placeholder shape (sha=<full SHA>) does not match. Finding the line
    in a template is still not this tool posting it, and it is not a start.
    """
    return START_REGISTRATION_RE.search(text) is not None


def legal_founder_declaration() -> dict[str, Any]:
    """In-memory declaration that meets the five conditions. Not a start."""
    return {
        "approval_is_a_start": False,
        "start_registration_present": False,
        "supervision_policy": {
            "declared_before_start": True,
            "yellow_min_seconds": YELLOW_MIN_SECONDS,
            "yellow_max_seconds": RED_MIN_SECONDS,
            "red_exclusive_min_seconds": RED_MIN_SECONDS,
            "clock": "monotonic",
        },
        "supervision_writes": {
            "declared": True,
            "max_gap_seconds": SUPERVISION_WRITE_MAX_SECONDS,
        },
        "supervisor_watchdog": {
            "present": True,
            "kind": SUPERVISOR_WATCHDOG_KIND,
            "crash_recorded_within_seconds": SUPERVISOR_WATCHDOG_MAX_SECONDS,
        },
        "evidence": {
            "publication": "public",
            "final_metrics": True,
            "log_summary": True,
            "sha_list": True,
        },
        "failure_attribution": {
            "ways": ["business", "host", "supervision"],
            "terminal": "none",
            "unknown_root_cause_allowed": False,
        },
        "production": {
            "claimed": "NOT_ACCEPTED",
            "pass_is_production_readiness": False,
        },
    }


def _founder_condition(condition_id: str, *, declared: bool, satisfied: bool, detail: str) -> dict[str, Any]:
    return {
        "id": condition_id,
        "required": True,
        "declared": declared,
        "satisfied": satisfied,
        "detail": detail,
    }


def _open_condition(condition_id: str, detail: str) -> dict[str, Any]:
    declared = detail != "not_declared"
    return _founder_condition(condition_id, declared=declared, satisfied=False, detail=detail)


def _closed_condition(condition_id: str) -> dict[str, Any]:
    return _founder_condition(condition_id, declared=True, satisfied=True, detail="satisfied")


def _assess_supervision_policy(raw: Any) -> dict[str, Any]:
    condition_id = "supervision_policy"
    if not isinstance(raw, dict):
        return _open_condition(condition_id, "not_declared")
    if raw.get("declared_before_start") is not True:
        return _open_condition(condition_id, "not_declared")
    yellow_min = raw.get("yellow_min_seconds")
    yellow_max = raw.get("yellow_max_seconds")
    red_min = raw.get("red_exclusive_min_seconds")
    numbers_ok = (
        _is_number(yellow_min)
        and float(yellow_min) == YELLOW_MIN_SECONDS
        and _is_number(yellow_max)
        and float(yellow_max) == RED_MIN_SECONDS
        and _is_number(red_min)
        and float(red_min) == RED_MIN_SECONDS
    )
    clock_ok = _token_key(raw.get("clock")) == "monotonic"
    if not numbers_ok:
        return _open_condition(condition_id, "band_mismatch")
    if not clock_ok:
        return _open_condition(condition_id, "clock_not_monotonic")
    return _closed_condition(condition_id)


def _assess_supervisor_watchdog(raw: Any) -> str:
    """Return a condition detail for the supervisor-watchdog half."""
    if not isinstance(raw, dict):
        return "supervisor_watchdog_missing"
    kind = _token_key(raw.get("kind"))
    if kind in SOAK_DUT_WATCHDOG_KINDS:
        return "soak_dut_watchdog_is_not_supervisor_watchdog"
    seconds = raw.get("crash_recorded_within_seconds")
    present = raw.get("present") is True and kind == SUPERVISOR_WATCHDOG_KIND
    if not present:
        return "supervisor_watchdog_missing"
    if not _is_number(seconds) or float(seconds) < 0 or float(seconds) > SUPERVISOR_WATCHDOG_MAX_SECONDS:
        return "crash_record_too_slow"
    return "satisfied"


def _assess_cadence_and_watchdog(writes: Any, watchdog: Any) -> dict[str, Any]:
    condition_id = "supervision_cadence_and_supervisor_watchdog"
    if writes is None and watchdog is None:
        return _open_condition(condition_id, "not_declared")
    if not isinstance(writes, dict) or writes.get("declared") is not True:
        cadence = "write_gap_too_wide" if isinstance(writes, dict) else "not_declared"
    else:
        gap = writes.get("max_gap_seconds")
        cadence = "satisfied" if _is_number(gap) and 0 < float(gap) <= SUPERVISION_WRITE_MAX_SECONDS else "write_gap_too_wide"
    watch = _assess_supervisor_watchdog(watchdog)
    if cadence == "satisfied" and watch == "satisfied":
        return _closed_condition(condition_id)
    if watch != "satisfied":
        return _open_condition(condition_id, watch)
    return _open_condition(condition_id, cadence)


def _assess_public_evidence(raw: Any) -> dict[str, Any]:
    condition_id = "public_evidence"
    if not isinstance(raw, dict):
        return _open_condition(condition_id, "not_declared")
    publication = _token_key(raw.get("publication"))
    parts = all(raw.get(key) is True for key in ("final_metrics", "log_summary", "sha_list"))
    if publication == LOCAL_ONLY_TOKEN:
        return _open_condition(condition_id, "local_only_refused")
    if publication != "public":
        return _open_condition(condition_id, "not_declared")
    if not parts:
        return _open_condition(condition_id, "public_parts_missing")
    return _closed_condition(condition_id)


def _assess_attribution(raw: Any) -> dict[str, Any]:
    condition_id = "three_way_attribution"
    if not isinstance(raw, dict):
        return _open_condition(condition_id, "not_declared")
    ways = raw.get("ways")
    ways_ok = (
        isinstance(ways, list)
        and len(ways) == 3
        and {_token_key(item) for item in ways} == ATTRIBUTION_WAYS
        and all(isinstance(item, str) for item in ways)
    )
    terminal = _token_key(raw.get("terminal") or "none")
    allowed = raw.get("unknown_root_cause_allowed") is True
    if allowed or terminal in UNKNOWN_ROOT_TOKENS or terminal not in ATTRIBUTION_TERMINALS:
        return _open_condition(condition_id, "unknown_root_cause_refused")
    if not ways_ok:
        return _open_condition(condition_id, "ways_incomplete")
    return _closed_condition(condition_id)


def _assess_production(raw: Any) -> dict[str, Any]:
    condition_id = "not_production_7x24"
    if not isinstance(raw, dict):
        return _open_condition(condition_id, "not_declared")
    claimed = _token_key(raw.get("claimed"))
    if raw.get("pass_is_production_readiness") is True:
        return _open_condition(condition_id, "pass_claimed_as_readiness")
    if claimed in {"accepted", "pass", "production_accepted"}:
        return _open_condition(condition_id, "production_claim_refused")
    if claimed != "not_accepted":
        return _open_condition(condition_id, "not_declared")
    return _closed_condition(condition_id)


def _founder_shell(conditions: list[dict[str, Any]], **flags: Any) -> dict[str, Any]:
    missing = [item["id"] for item in conditions if item.get("satisfied") is not True]
    satisfied = not missing and len(conditions) == len(FOUNDER_CONDITION_IDS)
    block: dict[str, Any] = {
        "rule": "five_founder_conditions_before_start",
        "approval_exists": True,
        "approval_conditional": True,
        "approval_issue": FOUNDER_APPROVAL_ISSUE,
        "approval_comment_id": FOUNDER_APPROVAL_COMMENT_ID,
        "approval_utc": FOUNDER_APPROVAL_UTC,
        "approval_target_pr": FOUNDER_APPROVAL_PR,
        "approval_is_a_start": False,
        "approval_is_a_pass": False,
        "approval_claimed_as_start": False,
        "approval_without_conditions_is_a_start": False,
        "approval_without_start_registration_is_a_start": False,
        "start_registration_present": False,
        "start_registration_posted_to_issue_9": False,
        "start_registration_claimed": False,
        "conditions_satisfied": satisfied,
        "missing_conditions": missing,
        "local_only_counts_as_public_evidence": False,
        "local_only_refused": False,
        "unknown_root_cause_allowed": False,
        "unknown_root_cause_refused": False,
        "soak_dut_watchdog_counts_as_supervisor_watchdog": False,
        "supervisor_watchdog_refused": False,
        "supervisor_watchdog_kind_required": SUPERVISOR_WATCHDOG_KIND,
        "supervision_write_max_seconds": SUPERVISION_WRITE_MAX_SECONDS,
        "supervisor_watchdog_max_seconds": SUPERVISOR_WATCHDOG_MAX_SECONDS,
        "yellow_min_seconds": YELLOW_MIN_SECONDS,
        "yellow_max_seconds": RED_MIN_SECONDS,
        "red_exclusive_min_seconds": RED_MIN_SECONDS,
        "clock_required": "monotonic",
        "a_72h_pass_is_production_readiness": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "binds_clock_start": False,
        "declarations_are_not_a_start": True,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "conditions": conditions,
    }
    for key, value in flags.items():
        if key in block and key not in {
            "approval_is_a_start",
            "approval_is_a_pass",
            "approval_without_conditions_is_a_start",
            "approval_without_start_registration_is_a_start",
            "start_registration_present",
            "start_registration_posted_to_issue_9",
            "local_only_counts_as_public_evidence",
            "unknown_root_cause_allowed",
            "soak_dut_watchdog_counts_as_supervisor_watchdog",
            "a_72h_pass_is_production_readiness",
            "production_7x24",
            "can_start_clock",
            "can_accept_l2_2",
            "can_close_l2_2",
            "binds_clock_start",
            "declarations_are_not_a_start",
            "l2_2_status",
            "clock_state",
            "clock_effect",
            "conditions_satisfied",
            "missing_conditions",
            "rule",
        }:
            block[key] = value
    by_id = {item["id"]: item for item in conditions}
    block["local_only_refused"] = by_id.get("public_evidence", {}).get("detail") == "local_only_refused"
    block["unknown_root_cause_refused"] = by_id.get("three_way_attribution", {}).get("detail") == "unknown_root_cause_refused"
    block["supervisor_watchdog_refused"] = (
        by_id.get("supervision_cadence_and_supervisor_watchdog", {}).get("detail") in WATCHDOG_REFUSAL_DETAILS
    )
    block["conditions_satisfied"] = satisfied
    block["missing_conditions"] = missing
    return block


def assess_founder_start(claim: dict[str, Any] | None) -> dict[str, Any]:
    """Score a founder-start claim. The approval is not a start.

    conditions_satisfied is true only when all five declarations are legal.
    That flag does not start the clock, does not emit PASS, and does not
    accept production 7x24. LOCAL_ONLY is not public evidence. An unknown
    root cause is not a terminal attribution. The soak-DUT stall watchdog
    is not a watchdog of the supervisor.
    """
    if claim is None:
        claim = {}
    if not isinstance(claim, dict):
        claim = {}
    conditions = [
        _assess_supervision_policy(claim.get("supervision_policy")),
        _assess_cadence_and_watchdog(claim.get("supervision_writes"), claim.get("supervisor_watchdog")),
        _assess_public_evidence(claim.get("evidence")),
        _assess_attribution(claim.get("failure_attribution")),
        _assess_production(claim.get("production")),
    ]
    return _founder_shell(
        conditions,
        approval_claimed_as_start=claim.get("approval_is_a_start") is True,
        start_registration_claimed=claim.get("start_registration_present") is True,
    )


def _validate_founder_start(raw: Any) -> None:
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise CaptureError("founder_start must be an object")
    for key in ("approval_is_a_start", "start_registration_present"):
        if key in raw and not isinstance(raw[key], bool):
            raise CaptureError(f"founder_start.{key} must be a bool")
    for key in (
        "supervision_policy",
        "supervision_writes",
        "supervisor_watchdog",
        "evidence",
        "failure_attribution",
        "production",
    ):
        if key in raw and raw[key] is not None and not isinstance(raw[key], dict):
            raise CaptureError(f"founder_start.{key} must be an object or null")
    policy = raw.get("supervision_policy")
    if isinstance(policy, dict) and "declared_before_start" in policy and not isinstance(
        policy.get("declared_before_start"), bool
    ):
        raise CaptureError("founder_start.supervision_policy.declared_before_start must be a bool")
    evidence = raw.get("evidence")
    if isinstance(evidence, dict):
        for key in ("final_metrics", "log_summary", "sha_list"):
            if key in evidence and not isinstance(evidence.get(key), bool):
                raise CaptureError(f"founder_start.evidence.{key} must be a bool")
    attribution = raw.get("failure_attribution")
    if isinstance(attribution, dict):
        if "ways" in attribution and not isinstance(attribution.get("ways"), list):
            raise CaptureError("founder_start.failure_attribution.ways must be a list")
        if "unknown_root_cause_allowed" in attribution and not isinstance(
            attribution.get("unknown_root_cause_allowed"), bool
        ):
            raise CaptureError("founder_start.failure_attribution.unknown_root_cause_allowed must be a bool")
    production = raw.get("production")
    if isinstance(production, dict) and "pass_is_production_readiness" in production and not isinstance(
        production.get("pass_is_production_readiness"), bool
    ):
        raise CaptureError("founder_start.production.pass_is_production_readiness must be a bool")


def _forged_production_claim(doc: dict[str, Any]) -> bool:
    production = str(doc.get("claimed_production_7x24") or "").strip().upper().replace(" ", "_")
    if production in {"", "NOT_ACCEPTED", "NOT_STARTED", "INCOMPLETE", "UNSCORED"}:
        return False
    return production in {"ACCEPTED", "PASS", "PRODUCTION_ACCEPTED"} or "ACCEPTED" in production


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

    founder_claim = doc.get("founder_start") if isinstance(doc.get("founder_start"), dict) else None
    if founder_claim is not None and _forged_production_claim(doc):
        production = dict(founder_claim.get("production") or {})
        production["claimed"] = "ACCEPTED"
        founder_claim = dict(founder_claim)
        founder_claim["production"] = production
    founder = assess_founder_start(founder_claim if "founder_start" in doc else None)
    if not founder["conditions_satisfied"]:
        blockers.append("founder_start_conditions_unsatisfied")
    if founder["approval_claimed_as_start"] or founder["start_registration_claimed"]:
        blockers.append("approval_is_not_a_start")
    if founder["local_only_refused"]:
        blockers.append("local_only_evidence_refused")
    if founder["unknown_root_cause_refused"]:
        blockers.append("unknown_root_cause_refused")
    if founder["supervisor_watchdog_refused"]:
        blockers.append("supervisor_watchdog_required")

    watch_claim = doc.get("supervisor_watchdog_claim") if isinstance(doc.get("supervisor_watchdog_claim"), dict) else None
    supervisor_honesty = offline_supervisor_watchdog_probe(claim=watch_claim)
    blockers.append("supervisor_watchdog_offline_probe_is_not_condition_2")
    if supervisor_honesty.get("stall_watchdog_claimed_as_supervisor_watchdog") is True:
        blockers.append("supervisor_watchdog_required")
    if supervisor_honesty.get("offline_probe_claimed_as_supervisor_watchdog") is True:
        blockers.append("offline_probe_is_not_supervisor_watchdog")
    if supervisor_honesty.get("condition_2_claimed_satisfied") is True:
        blockers.append("condition_2_unsatisfied")
    if supervisor_honesty.get("pass_or_start_claimed") is True:
        blockers.append("forged_pass")

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
                "cycles x interval is not the wall. cycles_exit0 is process success only. "
                "The Issue #9 conditional approval is not a start. "
                "LOCAL_ONLY evidence does not count. "
                "Unknown root cause is not a terminal attribution. "
                "A soak-DUT stall watchdog is not a watchdog of the supervisor. "
                "An offline synthetic supervisor probe is not that watchdog, "
                "does not satisfy founder condition 2, and is not a start. "
                "A 72h result is not production readiness."
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
        "founder_start_conditions": founder,
        "supervisor_watchdog_honesty": supervisor_honesty,
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


def _founder_block_violations(block: Any) -> list[str]:
    """Reject a report that pretends the founder approval started or satisfied the gate."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["founder_start_conditions"]
    if block.get("rule") != "five_founder_conditions_before_start":
        violations.append("founder_start_conditions")
    constants = {
        "approval_exists": True,
        "approval_conditional": True,
        "approval_issue": FOUNDER_APPROVAL_ISSUE,
        "approval_comment_id": FOUNDER_APPROVAL_COMMENT_ID,
        "approval_utc": FOUNDER_APPROVAL_UTC,
        "approval_target_pr": FOUNDER_APPROVAL_PR,
        "approval_is_a_start": False,
        "approval_is_a_pass": False,
        "approval_without_conditions_is_a_start": False,
        "approval_without_start_registration_is_a_start": False,
        "start_registration_present": False,
        "start_registration_posted_to_issue_9": False,
        "local_only_counts_as_public_evidence": False,
        "unknown_root_cause_allowed": False,
        "soak_dut_watchdog_counts_as_supervisor_watchdog": False,
        "supervisor_watchdog_kind_required": SUPERVISOR_WATCHDOG_KIND,
        "supervision_write_max_seconds": SUPERVISION_WRITE_MAX_SECONDS,
        "supervisor_watchdog_max_seconds": SUPERVISOR_WATCHDOG_MAX_SECONDS,
        "yellow_min_seconds": YELLOW_MIN_SECONDS,
        "yellow_max_seconds": RED_MIN_SECONDS,
        "red_exclusive_min_seconds": RED_MIN_SECONDS,
        "clock_required": "monotonic",
        "a_72h_pass_is_production_readiness": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "binds_clock_start": False,
        "declarations_are_not_a_start": True,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            if key == "approval_is_a_start" or key in {
                "approval_is_a_pass",
                "approval_without_conditions_is_a_start",
                "approval_without_start_registration_is_a_start",
                "start_registration_present",
                "start_registration_posted_to_issue_9",
            }:
                violations.append("approval_is_not_a_start")
            elif key == "local_only_counts_as_public_evidence":
                violations.append("local_only_refused")
            elif key == "unknown_root_cause_allowed":
                violations.append("unknown_root_cause_refused")
            elif key == "soak_dut_watchdog_counts_as_supervisor_watchdog":
                violations.append("supervisor_watchdog_required")
            elif key in {"a_72h_pass_is_production_readiness", "production_7x24"}:
                violations.append("production_claim")
            elif key in {"can_start_clock", "binds_clock_start"}:
                violations.append("forged_clock_start")
            elif key == "can_accept_l2_2":
                violations.append("forged_accept")
            elif key == "can_close_l2_2":
                violations.append("forged_close")
            elif key == "l2_2_status":
                violations.append("status")
            elif key == "clock_state" or key == "clock_effect":
                violations.append("clock_state")
            else:
                violations.append("founder_start_conditions")
    if not isinstance(block.get("approval_claimed_as_start"), bool):
        violations.append("founder_start_conditions")
    if not isinstance(block.get("start_registration_claimed"), bool):
        violations.append("founder_start_conditions")
    if block.get("approval_claimed_as_start") is True and block.get("approval_is_a_start") is not False:
        violations.append("approval_is_not_a_start")
    conditions = block.get("conditions")
    if not isinstance(conditions, list) or [item.get("id") if isinstance(item, dict) else None for item in conditions] != list(
        FOUNDER_CONDITION_IDS
    ):
        violations.append("founder_start_conditions")
        return violations
    missing_expected: list[str] = []
    for item in conditions:
        if item.get("required") is not True or not isinstance(item.get("declared"), bool) or not isinstance(item.get("satisfied"), bool):
            violations.append("founder_start_conditions")
            continue
        detail = item.get("detail")
        if detail not in FOUNDER_CONDITION_DETAILS:
            violations.append("founder_start_conditions")
            continue
        if detail == "not_declared" and (item.get("declared") is not False or item.get("satisfied") is not False):
            violations.append("founder_conditions_missing")
        elif detail == "satisfied" and (item.get("declared") is not True or item.get("satisfied") is not True):
            violations.append("founder_conditions_missing")
        elif detail not in {"not_declared", "satisfied"} and (
            item.get("declared") is not True or item.get("satisfied") is not False
        ):
            violations.append("founder_conditions_missing")
        if item.get("satisfied") is not True:
            missing_expected.append(item["id"])
        if detail == "local_only_refused" and item.get("satisfied") is True:
            violations.append("local_only_refused")
        if detail == "unknown_root_cause_refused" and item.get("satisfied") is True:
            violations.append("unknown_root_cause_refused")
        if detail in WATCHDOG_REFUSAL_DETAILS and item.get("satisfied") is True:
            violations.append("supervisor_watchdog_required")
    by_id = {item["id"]: item for item in conditions}
    if block.get("local_only_refused") is not (by_id["public_evidence"].get("detail") == "local_only_refused"):
        violations.append("local_only_refused")
    if block.get("local_only_counts_as_public_evidence") is True or (
        by_id["public_evidence"].get("detail") == "local_only_refused" and by_id["public_evidence"].get("satisfied") is True
    ):
        violations.append("local_only_refused")
    if block.get("unknown_root_cause_refused") is not (
        by_id["three_way_attribution"].get("detail") == "unknown_root_cause_refused"
    ):
        violations.append("unknown_root_cause_refused")
    if block.get("unknown_root_cause_allowed") is True or (
        by_id["three_way_attribution"].get("detail") == "unknown_root_cause_refused"
        and by_id["three_way_attribution"].get("satisfied") is True
    ):
        violations.append("unknown_root_cause_refused")
    watchdog_detail = by_id["supervision_cadence_and_supervisor_watchdog"].get("detail")
    if block.get("supervisor_watchdog_refused") is not (watchdog_detail in WATCHDOG_REFUSAL_DETAILS):
        violations.append("supervisor_watchdog_required")
    if block.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is True or (
        watchdog_detail == "soak_dut_watchdog_is_not_supervisor_watchdog"
        and by_id["supervision_cadence_and_supervisor_watchdog"].get("satisfied") is True
    ):
        violations.append("supervisor_watchdog_required")
    if block.get("missing_conditions") != missing_expected:
        violations.append("founder_conditions_missing")
    if block.get("conditions_satisfied") is not (missing_expected == []):
        violations.append("founder_conditions_missing")
    if block.get("conditions_satisfied") is True and missing_expected:
        violations.append("founder_conditions_missing")
    if block.get("conditions_satisfied") is True and any(item.get("detail") != "satisfied" for item in conditions):
        violations.append("founder_conditions_missing")
    return violations


def _supervisor_case_common() -> dict[str, Any]:
    return {
        "condition_2_satisfied": False,
        "counts_as_supervisor_watchdog": False,
        "live_process": False,
        "is_a_start": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
    }


def _canonical_supervisor_cases() -> list[dict[str, Any]]:
    """Stable classifications. No paths, no clock, no live process."""
    common = _supervisor_case_common()
    alive = {
        "label": "supervisor_alive",
        "classification": "supervisor_alive",
        "heartbeat_present": True,
        "heartbeat_fresh": True,
        "pid": None,
        "other_process_record_present": False,
        "crash_recorded_within_seconds": None,
        "record_within_max_seconds": False,
    }
    missing = {
        "label": "supervisor_crash_unrecorded",
        "classification": "supervisor_crash_unrecorded",
        "heartbeat_present": False,
        "heartbeat_fresh": False,
        "pid": None,
        "crash_marker_present": True,
        "other_process_record_present": False,
        "crash_recorded_within_seconds": None,
        "record_within_max_seconds": False,
    }
    slow = {
        "label": "supervisor_crash_record_too_slow",
        "classification": "supervisor_crash_unrecorded",
        "heartbeat_present": False,
        "heartbeat_fresh": False,
        "pid": None,
        "crash_marker_present": True,
        "other_process_record_present": True,
        "crash_recorded_within_seconds": SUPERVISOR_SLOW_RECORD_SECONDS,
        "record_within_max_seconds": False,
    }
    alive.update(common)
    missing.update(common)
    slow.update(common)
    return [alive, missing, slow]


def _supervisor_closed_flags() -> dict[str, Any]:
    """Flags a report must not flip. The probe does not close founder condition 2."""
    return {
        "condition_2_satisfied": False,
        "offline_probe_satisfies_condition_2": False,
        "offline_probe_is_supervisor_watchdog": False,
        "offline_probe_is_a_start": False,
        "is_supervisor_watchdog_of_live_supervisor": False,
        "is_a_start": False,
        "counts_as_start": False,
        "counts_as_pass": False,
        "soak_dut_stall_watchdog_is_supervisor_watchdog": False,
        "soak_dut_watchdog_counts_as_supervisor_watchdog": False,
        "live_supervisor_process": False,
        "live_soak_process": False,
        "live_watchdog_process": False,
        "binds_clock_start": False,
        "implies_l2_2_pass": False,
        "implies_l2_2_acceptance": False,
        "a_72h_pass_is_production_readiness": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "soak_launched": False,
        "documented_soak_argv_executed": False,
        "declarations_are_not_a_start": True,
    }


def _path_under_progress(path: Path) -> bool:
    progress = Path(__file__).resolve().parents[1] / "docs" / "progress"
    try:
        path.resolve().relative_to(progress.resolve())
    except (OSError, ValueError):
        return False
    return True


def _read_synthetic_json(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _heartbeat_ok(path: Path, *, now_s: float) -> bool:
    doc = _read_synthetic_json(path)
    if doc is None:
        return False
    if doc.get("synthetic") is not True or doc.get("role") != "supervisor_heartbeat":
        return False
    if doc.get("state") != "alive" or doc.get("utc") != SUPERVISOR_PROBE_UTC or doc.get("pid") is not None:
        return False
    try:
        age = now_s - path.stat().st_mtime
    except OSError:
        return False
    return 0 <= age < SUPERVISOR_ALIVE_MAX_AGE_SECONDS


def _crash_marker_ok(path: Path) -> bool:
    doc = _read_synthetic_json(path)
    if doc is None:
        return False
    return (
        doc.get("synthetic") is True
        and doc.get("role") == "supervisor_crash_marker"
        and doc.get("state") == "crashed"
        and doc.get("utc") == SUPERVISOR_PROBE_UTC
        and doc.get("pid") is None
    )


def _slow_record_ok(crash: Path, record: Path) -> bool:
    doc = _read_synthetic_json(record)
    if doc is None or not _crash_marker_ok(crash):
        return False
    if doc.get("synthetic") is not True or doc.get("role") != "other_process_record":
        return False
    if doc.get("recorded_after_seconds") != SUPERVISOR_SLOW_RECORD_SECONDS:
        return False
    try:
        gap = record.stat().st_mtime - crash.stat().st_mtime
    except OSError:
        return False
    return gap > SUPERVISOR_WATCHDOG_MAX_SECONDS


def _classify_supervisor_temp_files(*, now: float | None = None) -> dict[str, Any]:
    """Write temp files and classify them. No live soak and no live supervisor process."""
    now_s = time.time() if now is None else float(now)
    alive_body = {
        "synthetic": True,
        "label": "scaffold",
        "evidence_class": "not_host",
        "role": "supervisor_heartbeat",
        "state": "alive",
        "utc": SUPERVISOR_PROBE_UTC,
        "pid": None,
    }
    crash_body = {
        "synthetic": True,
        "label": "scaffold",
        "evidence_class": "not_host",
        "role": "supervisor_crash_marker",
        "state": "crashed",
        "utc": SUPERVISOR_PROBE_UTC,
        "pid": None,
    }
    slow_body = {
        "synthetic": True,
        "label": "scaffold",
        "evidence_class": "not_host",
        "role": "other_process_record",
        "recorded_after_seconds": SUPERVISOR_SLOW_RECORD_SECONDS,
        "utc": SUPERVISOR_PROBE_UTC,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="l2_2_supervisor_hook_") as tmp_name:
            tmp = Path(tmp_name)
            if _path_under_progress(tmp):
                return {"ok": False, "detail": "probe_in_repo", "cases": []}
            alive = tmp / "supervisor_alive.json"
            crash = tmp / "supervisor_crash.json"
            slow_crash = tmp / "supervisor_crash_slow.json"
            slow_record = tmp / "other_process_record.json"
            alive.write_text(json.dumps(alive_body), encoding="utf-8")
            crash.write_text(json.dumps(crash_body), encoding="utf-8")
            slow_crash.write_text(json.dumps(crash_body), encoding="utf-8")
            slow_record.write_text(json.dumps(slow_body), encoding="utf-8")
            os.utime(alive, (now_s, now_s))
            crash_at = now_s - SUPERVISOR_CRASH_OFFSET_SECONDS
            os.utime(crash, (crash_at, crash_at))
            os.utime(slow_crash, (crash_at, crash_at))
            recorded_at = crash_at + float(SUPERVISOR_SLOW_RECORD_SECONDS)
            os.utime(slow_record, (recorded_at, recorded_at))
            missing_record = tmp / "missing_other_process_record.json"
            classified = (
                _heartbeat_ok(alive, now_s=now_s)
                and _crash_marker_ok(crash)
                and not missing_record.is_file()
                and _slow_record_ok(slow_crash, slow_record)
            )
    except OSError:
        return {"ok": False, "detail": "probe_io", "cases": []}
    if not classified:
        return {"ok": False, "detail": "classification_failed", "cases": []}
    return {"ok": True, "detail": SUPERVISOR_PROBE_DETAIL, "cases": _canonical_supervisor_cases()}


def _claim_names_stall(claim: dict[str, Any]) -> bool:
    if claim.get("stall_watchdog_is_supervisor_watchdog") is True:
        return True
    if claim.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is True:
        return True
    if claim.get("soak_dut_stall_watchdog_is_supervisor_watchdog") is True:
        return True
    if _token_key(claim.get("kind")) in SOAK_DUT_WATCHDOG_KINDS:
        return True
    return "stall_watchdog" in str(claim.get("tool") or "")


def _claim_names_offline_probe(claim: dict[str, Any]) -> bool:
    if claim.get("offline_probe_is_supervisor_watchdog") is True:
        return True
    if claim.get("offline_probe_satisfies_condition_2") is True:
        return True
    return _token_key(claim.get("kind")) in OFFLINE_PROBE_KINDS


def _claim_says_condition_2(claim: dict[str, Any]) -> bool:
    return (
        claim.get("condition_2_satisfied") is True
        or claim.get("satisfies_founder_condition_2") is True
        or claim.get("conditions_satisfied") is True
        or claim.get("offline_probe_satisfies_condition_2") is True
    )


def _claim_says_pass_or_start(claim: dict[str, Any]) -> bool:
    status = str(claim.get("l2_2_status") or "").strip().upper().replace(" ", "_")
    clock = str(claim.get("clock_state") or "").strip().upper().replace(" ", "_")
    production = str(claim.get("production_7x24") or "").strip().upper().replace(" ", "_")
    if status in {"PASS", "ACCEPTED", "STARTED"} or status.startswith("PASS"):
        return True
    if clock in {"STARTED", "WALL_OBSERVED"}:
        return True
    if production in {"ACCEPTED", "PASS", "PRODUCTION_ACCEPTED"} or "ACCEPTED" in production:
        return True
    return claim.get("can_start_clock") is True or claim.get("is_a_start") is True


def _annotate_supervisor_claim(block: dict[str, Any], claim: dict[str, Any] | None) -> None:
    """Record a pretense. Closed flags are applied again by the caller."""
    block["stall_watchdog_claimed_as_supervisor_watchdog"] = False
    block["offline_probe_claimed_as_supervisor_watchdog"] = False
    block["condition_2_claimed_satisfied"] = False
    block["pass_or_start_claimed"] = False
    if not isinstance(claim, dict):
        return
    block["stall_watchdog_claimed_as_supervisor_watchdog"] = _claim_names_stall(claim)
    block["offline_probe_claimed_as_supervisor_watchdog"] = _claim_names_offline_probe(claim)
    block["condition_2_claimed_satisfied"] = _claim_says_condition_2(claim)
    block["pass_or_start_claimed"] = _claim_says_pass_or_start(claim)


def _supervisor_watchdog_shell(classified: dict[str, Any]) -> dict[str, Any]:
    detail = classified.get("detail")
    if detail not in SUPERVISOR_PROBE_DETAILS:
        detail = "probe_failed"
    cases = classified.get("cases") if detail == SUPERVISOR_PROBE_DETAIL else []
    if not isinstance(cases, list):
        cases = []
        detail = "probe_failed"
    block: dict[str, Any] = {
        "rule": SUPERVISOR_PROBE_RULE,
        "tool": SUPERVISOR_PROBE_TOOL,
        "action": SUPERVISOR_PROBE_ACTION,
        "dut": SUPERVISOR_PROBE_DUT,
        "soak_dut_watchdog_tool": SOAK_DUT_STALL_TOOL,
        "required_watchdog_kind": SUPERVISOR_WATCHDOG_KIND,
        "supervisor_watchdog_max_seconds": SUPERVISOR_WATCHDOG_MAX_SECONDS,
        "supervision_write_max_seconds": SUPERVISION_WRITE_MAX_SECONDS,
        "founder_condition_id": "supervision_cadence_and_supervisor_watchdog",
        "founder_condition_2": SUPERVISOR_CONDITION_2,
        "hole": SUPERVISOR_PROBE_HOLE,
        "note": SUPERVISOR_PROBE_NOTE,
        "ok": classified.get("ok") is True and detail == SUPERVISOR_PROBE_DETAIL,
        "detail": detail,
        "cases": cases if detail == SUPERVISOR_PROBE_DETAIL else [],
    }
    block.update(_supervisor_closed_flags())
    return block


def offline_supervisor_watchdog_probe(
    claim: dict[str, Any] | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Classify synthetic supervisor-alive vs crash-unrecorded files.

    Uses a temp directory. Does not start a soak, does not start a supervisor
    process, and does not satisfy founder condition 2. A claim that this probe
    or the soak-DUT stall hook is the required watchdog is recorded and refused.
    """
    try:
        classified = _classify_supervisor_temp_files(now=now)
    except Exception:
        classified = {"ok": False, "detail": "probe_failed", "cases": []}
    block = _supervisor_watchdog_shell(classified)
    _annotate_supervisor_claim(block, claim)
    block.update(_supervisor_closed_flags())
    return block


def _supervisor_flag_violation(key: str, actual: Any) -> str:
    if key in {"condition_2_satisfied", "offline_probe_satisfies_condition_2"}:
        return "condition_2_unsatisfied"
    if key in {
        "offline_probe_is_supervisor_watchdog",
        "is_supervisor_watchdog_of_live_supervisor",
        "live_supervisor_process",
        "live_soak_process",
        "live_watchdog_process",
    }:
        return "offline_probe_is_not_supervisor_watchdog"
    if key in {"soak_dut_stall_watchdog_is_supervisor_watchdog", "soak_dut_watchdog_counts_as_supervisor_watchdog"}:
        return "supervisor_watchdog_required"
    if key in {"is_a_start", "offline_probe_is_a_start", "counts_as_start"}:
        return "offline_probe_is_not_a_start"
    if key == "counts_as_pass" or key == "implies_l2_2_pass":
        return "forged_pass"
    if key in {"a_72h_pass_is_production_readiness", "production_7x24"}:
        return "production_claim"
    if key in {"can_start_clock", "binds_clock_start"}:
        return "forged_clock_start"
    if key == "can_accept_l2_2":
        return "forged_accept"
    if key == "can_close_l2_2":
        return "forged_close"
    if key == "implies_l2_2_acceptance":
        return "forged_accept"
    if key == "l2_2_status":
        text = str(actual or "").strip().upper()
        if text == "PASS" or text.startswith("PASS") or text == "ACCEPTED":
            return "forged_pass"
        return "status"
    if key in {"clock_state", "clock_effect"}:
        return "clock_state"
    if key in {"soak_launched", "documented_soak_argv_executed"}:
        return "soak_launched"
    return "supervisor_watchdog_honesty"


def _supervisor_watchdog_honesty_violations(block: Any, *, require_success: bool = True) -> list[str]:
    """Reject a report that pretends the offline probe or the stall hook closed condition 2."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["supervisor_watchdog_honesty"]
    for key, expected in _supervisor_closed_flags().items():
        if block.get(key) != expected:
            violations.append(_supervisor_flag_violation(key, block.get(key)))
    constants = {
        "rule": SUPERVISOR_PROBE_RULE,
        "tool": SUPERVISOR_PROBE_TOOL,
        "action": SUPERVISOR_PROBE_ACTION,
        "dut": SUPERVISOR_PROBE_DUT,
        "soak_dut_watchdog_tool": SOAK_DUT_STALL_TOOL,
        "required_watchdog_kind": SUPERVISOR_WATCHDOG_KIND,
        "supervisor_watchdog_max_seconds": SUPERVISOR_WATCHDOG_MAX_SECONDS,
        "supervision_write_max_seconds": SUPERVISION_WRITE_MAX_SECONDS,
        "founder_condition_id": "supervision_cadence_and_supervisor_watchdog",
        "founder_condition_2": SUPERVISOR_CONDITION_2,
        "hole": SUPERVISOR_PROBE_HOLE,
        "note": SUPERVISOR_PROBE_NOTE,
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            if key == "tool" and "stall_watchdog" in str(block.get("tool") or ""):
                violations.append("supervisor_watchdog_required")
            else:
                violations.append("supervisor_watchdog_honesty")
    for key in (
        "stall_watchdog_claimed_as_supervisor_watchdog",
        "offline_probe_claimed_as_supervisor_watchdog",
        "condition_2_claimed_satisfied",
        "pass_or_start_claimed",
    ):
        if not isinstance(block.get(key), bool):
            violations.append("supervisor_watchdog_honesty")
    detail = block.get("detail")
    ok = block.get("ok")
    if require_success:
        if ok is not True or detail != SUPERVISOR_PROBE_DETAIL or block.get("cases") != _canonical_supervisor_cases():
            violations.append("supervisor_watchdog_honesty")
    else:
        if not isinstance(ok, bool) or detail not in SUPERVISOR_PROBE_DETAILS:
            violations.append("supervisor_watchdog_honesty")
        elif ok is True and (detail != SUPERVISOR_PROBE_DETAIL or block.get("cases") != _canonical_supervisor_cases()):
            violations.append("supervisor_watchdog_honesty")
        elif ok is not True and block.get("cases") not in ([], _canonical_supervisor_cases()):
            violations.append("supervisor_watchdog_honesty")
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
    violations.extend(_founder_block_violations(report.get("founder_start_conditions")))
    violations.extend(_supervisor_watchdog_honesty_violations(report.get("supervisor_watchdog_honesty")))
    blockers = gates.get("blockers") if isinstance(gates.get("blockers"), list) else []
    if "supervisor_watchdog_offline_probe_is_not_condition_2" not in blockers:
        violations.append("supervisor_watchdog_honesty")
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
