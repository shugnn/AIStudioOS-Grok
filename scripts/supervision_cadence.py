#!/usr/bin/env python3
"""Supervision cadence writer.

Writes supervision records on a configured interval. The intended production
bound is supervision_write_max_seconds = 600 (at least once every 10 minutes).
An interval above that bound is refused. A short offline exercise uses a
compressed interval so the writer can be shown to land on a schedule without
waiting 10 minutes.

That exercise is not a live started L2-2 supervisor. It does not demonstrate
the 10-minute cadence, it does not satisfy founder condition 2, and it does
not start the clock. A write later than 600 seconds does not meet the cadence
bound. scripts/stall_watchdog.py watches a soak DUT. scripts/supervisor_watchdog.py
records a crash. Neither one is this writer.

  python3 scripts/supervision_cadence.py --out /tmp/writes.jsonl --interval 0.2 --writes 3
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "docs" / "progress"
SCRIPT = Path(__file__).resolve()
TOOL = "scripts/supervision_cadence.py"
WRITE_SCHEMA = "aistudioos-grok.supervision-cadence.write.v1"
PRODUCTION_MAX_SECONDS = 600
EXERCISE_INTERVAL_SECONDS = 0.2
EXERCISE_WRITE_COUNT = 3
SCHEDULE_SLACK_SECONDS = 5.0
LATE_GAP_SECONDS = 601
BOUND_GAP_SECONDS = 600
CLI_MAX_PLANNED_SECONDS = 30.0
SUCCESS_DETAIL = "implementation_exists_short_interval_writes_on_schedule"
FAILURE_DETAILS = frozenset(
    {
        SUCCESS_DETAIL,
        "script_missing",
        "exercise_failed",
        "import_failed",
    }
)
HOLE = "time_compressed_exercise_is_not_a_live_10_minute_supervision_cadence"
NOTE = (
    "Implementation exists and a time-compressed offline exercise wrote supervision "
    "records on its short interval. That exercise is not a live started L2-2 supervisor, "
    "does not demonstrate a real supervision write at least once every 10 minutes, "
    "and does not satisfy founder condition 2. A write later than 600 seconds does not "
    "meet the cadence bound. scripts/stall_watchdog.py and scripts/supervisor_watchdog.py "
    "are not this writer."
)
WRITE_NOTE = (
    "This supervision write is an offline or configured-interval record. "
    "It does not demonstrate the 10-minute cadence and does not start L2-2."
)

Clock = Callable[[], float]
Sleeper = Callable[[float], None]
_CACHE: dict[str, Any] | None = None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _under_progress(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROGRESS.resolve())
    except (OSError, ValueError):
        return False
    return True


def _closed_flags() -> dict[str, Any]:
    return {
        "condition_2_satisfied": False,
        "offline_exercise_satisfies_condition_2": False,
        "time_compressed_exercise_satisfies_condition_2": False,
        "time_compressed_exercise_demonstrates_10_minute_cadence": False,
        "writes_on_schedule_demonstrate_10_minute_cadence": False,
        "bound_gap_demonstrates_10_minute_supervision_cadence": False,
        "demonstrates_10_minute_supervision_cadence": False,
        "dummy_tests_satisfy_condition_2": False,
        "scaffold_satisfies_condition_2": False,
        "implementation_satisfies_condition_2": False,
        "stall_watchdog_is_cadence_writer": False,
        "supervisor_watchdog_is_cadence_writer": False,
        "is_live_l2_2_supervisor": False,
        "is_supervisor_watchdog_of_live_supervisor": False,
        "is_live_l2_2_supervisor_watchdog": False,
        "live_supervisor_process": False,
        "live_soak_process": False,
        "soak_launched": False,
        "documented_soak_argv_executed": False,
        "is_a_start": False,
        "binds_clock_start": False,
        "implies_l2_2_pass": False,
        "implies_l2_2_acceptance": False,
        "a_72h_pass_is_production_readiness": False,
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "production_7x24": "NOT_ACCEPTED",
    }


def apply_closed_flags(block: dict[str, Any]) -> dict[str, Any]:
    """Force the honesty flags. A claim cannot open them."""
    block.update(_closed_flags())
    return block


def interval_allowed(interval: Any, *, production_max: float = PRODUCTION_MAX_SECONDS) -> bool:
    """True when the configured interval can meet the production bound."""
    return _is_number(interval) and 0 < float(interval) <= float(production_max)


def planned_duration_seconds(interval: float, writes: int) -> float:
    if writes < 2:
        return 0.0
    return float(interval) * (writes - 1)


def gap_within_bound(gap: Any, *, max_seconds: float = PRODUCTION_MAX_SECONDS) -> bool:
    """True when a gap is inside the cadence bound, including a first write at 0."""
    return _is_number(gap) and 0 <= float(gap) <= float(max_seconds)


def assess_gap(
    gap: Any,
    *,
    max_seconds: float = PRODUCTION_MAX_SECONDS,
    live_started: bool = False,
    time_compressed: bool = False,
    simulated_clock: bool = False,
) -> dict[str, Any]:
    """Classify one gap. A numeric meet is not the live 10-minute demonstration.

    A caller that claims this gap came from a live started supervisor is recorded
    and still does not open the honesty flags. This function does not start L2-2.
    """
    within = gap_within_bound(gap, max_seconds=max_seconds)
    later = _is_number(gap) and float(gap) > float(max_seconds)
    block: dict[str, Any] = {
        "gap_seconds": float(gap) if _is_number(gap) else None,
        "max_seconds": float(max_seconds),
        "meets_cadence_bound": within,
        "write_later_than_bound": later,
        "late_write_meets_cadence": False,
        "time_compressed": time_compressed is True,
        "simulated_clock": simulated_clock is True,
        "live_started_claimed": live_started is True,
    }
    block.update(_closed_flags())
    if live_started is True:
        block["pass_or_start_claimed"] = True
    return block


def _on_configured_schedule(gap: float, *, sequence: int, interval: float, slack: float) -> bool:
    if sequence <= 1:
        return gap == 0
    low = float(interval) - 0.05
    high = float(interval) + float(slack)
    return low <= gap <= high and gap <= PRODUCTION_MAX_SECONDS


def _record(
    *,
    sequence: int,
    planned: int,
    interval: float,
    gap: float,
    offset: float,
    slack: float,
    simulated: bool,
) -> dict[str, Any]:
    rounded_gap = round(gap, 6)
    rounded_offset = round(offset, 6)
    within = gap_within_bound(rounded_gap)
    body: dict[str, Any] = {
        "schema": WRITE_SCHEMA,
        "role": "supervision_write",
        "sequence": sequence,
        "write_count_planned": planned,
        "configured_interval_seconds": interval,
        "production_max_seconds": PRODUCTION_MAX_SECONDS,
        "gap_seconds": rounded_gap,
        "monotonic_offset_seconds": rounded_offset,
        "gap_within_production_bound": within,
        "on_configured_schedule": _on_configured_schedule(
            rounded_gap, sequence=sequence, interval=interval, slack=slack
        ),
        "time_compressed": interval < PRODUCTION_MAX_SECONDS,
        "simulated_clock": simulated,
        "note": WRITE_NOTE,
    }
    body.update(_closed_flags())
    return body


def _sleep_until(deadline: float, clock: Clock, sleep: Sleeper) -> None:
    while True:
        remaining = deadline - clock()
        if remaining <= 1e-4:
            return
        sleep(min(0.05, remaining))


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if _under_progress(path):
        raise ValueError("refusing_progress_write")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records)
    tmp = path.with_name(path.name + ".tmp")
    if _under_progress(tmp):
        raise ValueError("refusing_progress_write")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def emit_writes(
    path: Path,
    *,
    interval: float,
    writes: int,
    slack: float = SCHEDULE_SLACK_SECONDS,
    simulated: bool = False,
    clock: Clock | None = None,
    sleep: Sleeper | None = None,
    max_runtime: float | None = None,
) -> list[dict[str, Any]]:
    """Write `writes` supervision records spaced by `interval` seconds.

    A real sleep whose planned span exceeds the scaffold cap is refused before
    any sleep. A simulated clock may use the full 600-second bound. Neither
    path demonstrates the live 10-minute cadence.
    """
    if not isinstance(writes, int) or isinstance(writes, bool) or writes < 1:
        raise ValueError("write_count_refused")
    if not interval_allowed(interval):
        raise ValueError("interval_out_of_bound")
    planned = planned_duration_seconds(float(interval), writes)
    if simulated is not True and planned > CLI_MAX_PLANNED_SECONDS:
        raise ValueError("planned_duration_refused")
    if _under_progress(path):
        raise ValueError("refusing_progress_write")
    clock_fn = clock or time.monotonic
    sleep_fn = sleep or time.sleep
    start = clock_fn()
    previous: float | None = None
    records: list[dict[str, Any]] = []
    for sequence in range(1, writes + 1):
        if previous is not None:
            _sleep_until(previous + float(interval), clock_fn, sleep_fn)
        now = clock_fn()
        if max_runtime is not None and sequence > 1 and (now - start) > float(max_runtime):
            break
        gap = 0.0 if previous is None else now - previous
        previous = now
        records.append(
            _record(
                sequence=sequence,
                planned=writes,
                interval=float(interval),
                gap=gap,
                offset=now - start,
                slack=slack,
                simulated=simulated is True,
            )
        )
    if len(records) != writes:
        raise ValueError("max_runtime_cut_short")
    _write_jsonl(path, records)
    return records


def read_writes(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise ValueError("write_not_object")
        rows.append(parsed)
    return rows


def writes_on_schedule(
    records: list[dict[str, Any]],
    *,
    interval: float,
    slack: float = SCHEDULE_SLACK_SECONDS,
    write_count: int | None = None,
) -> bool:
    """True when consecutive gaps follow the configured interval inside the slack."""
    if write_count is not None and len(records) != write_count:
        return False
    if len(records) < 2:
        return False
    for index, record in enumerate(records):
        if record.get("role") != "supervision_write":
            return False
        if record.get("sequence") != index + 1:
            return False
        if record.get("condition_2_satisfied") is not False:
            return False
        if record.get("demonstrates_10_minute_supervision_cadence") is not False:
            return False
        if record.get("can_start_clock") is not False:
            return False
        if record.get("l2_2_status") != "NOT_STARTED":
            return False
        if record.get("clock_state") != "NOT_STARTED":
            return False
        if record.get("production_7x24") != "NOT_ACCEPTED":
            return False
        gap = record.get("gap_seconds")
        if not _is_number(gap):
            return False
        if not _on_configured_schedule(float(gap), sequence=index + 1, interval=interval, slack=slack):
            return False
        if not gap_within_bound(gap):
            return False
    return True


def run_offline_exercise() -> dict[str, Any]:
    """Short real-sleep writes plus a late-gap classification. No host soak.

    The returned dict may contain nothing a committed report should keep.
    Callers that commit a report use stable_scaffold_status.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="supervision_cadence_") as tmp_name:
            tmp = Path(tmp_name)
            if _under_progress(tmp):
                return {"ok": False, "detail": "exercise_failed"}
            out = tmp / "writes.jsonl"
            records = emit_writes(
                out,
                interval=EXERCISE_INTERVAL_SECONDS,
                writes=EXERCISE_WRITE_COUNT,
                simulated=False,
                max_runtime=8,
            )
            reread = read_writes(out)
            scheduled = writes_on_schedule(
                records,
                interval=EXERCISE_INTERVAL_SECONDS,
                write_count=EXERCISE_WRITE_COUNT,
            ) and writes_on_schedule(
                reread,
                interval=EXERCISE_INTERVAL_SECONDS,
                write_count=EXERCISE_WRITE_COUNT,
            )
            late = assess_gap(LATE_GAP_SECONDS)
            bound = assess_gap(BOUND_GAP_SECONDS)
            refused_long = False
            try:
                emit_writes(tmp / "too_slow.jsonl", interval=LATE_GAP_SECONDS, writes=2, simulated=True)
            except ValueError as exc:
                refused_long = str(exc) == "interval_out_of_bound"
            if not scheduled or not refused_long:
                return {"ok": False, "detail": "exercise_failed"}
            if (
                late.get("meets_cadence_bound") is not False
                or late.get("write_later_than_bound") is not True
                or late.get("late_write_meets_cadence") is not False
                or late.get("demonstrates_10_minute_supervision_cadence") is not False
                or late.get("condition_2_satisfied") is not False
            ):
                return {"ok": False, "detail": "exercise_failed"}
            if (
                bound.get("meets_cadence_bound") is not True
                or bound.get("write_later_than_bound") is not False
                or bound.get("demonstrates_10_minute_supervision_cadence") is not False
                or bound.get("condition_2_satisfied") is not False
                or bound.get("is_supervisor_watchdog_of_live_supervisor") is not False
                or bound.get("can_start_clock") is not False
            ):
                return {"ok": False, "detail": "exercise_failed"}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"ok": False, "detail": "exercise_failed"}
    return {
        "ok": True,
        "detail": SUCCESS_DETAIL,
        "writes_on_schedule_passed": True,
        "late_write_meets_cadence": False,
        "bound_gap_within_numeric_bound": True,
    }


def _refused_claims() -> list[dict[str, Any]]:
    common = _closed_flags()
    specs = (
        ("time_compressed_called_10_minute_cadence", "time_compressed_claimed_as_10_minute_cadence"),
        ("offline_exercise_called_condition_2", "offline_exercise_claimed_as_condition_2"),
        ("stall_watchdog_called_cadence_writer", "stall_watchdog_claimed_as_cadence_writer"),
        ("crash_watchdog_called_cadence_writer", "crash_watchdog_claimed_as_cadence_writer"),
    )
    rows: list[dict[str, Any]] = []
    for label, flag in specs:
        row: dict[str, Any] = {"label": label, flag: True}
        row.update(common)
        rows.append(row)
    return rows


def _scaffold_shell(detail: str, *, ok: bool, implementation_present: bool) -> dict[str, Any]:
    if detail not in FAILURE_DETAILS:
        detail = "exercise_failed"
    passed = ok is True and detail == SUCCESS_DETAIL
    block: dict[str, Any] = {
        "ok": passed,
        "tool": TOOL,
        "action": "time_compressed_offline_writes",
        "dut": "offline_exercise",
        "detail": detail,
        "implementation_present": implementation_present and passed,
        "writes_on_schedule_passed": passed,
        "exercise_interval_seconds": EXERCISE_INTERVAL_SECONDS,
        "exercise_write_count": EXERCISE_WRITE_COUNT,
        "schedule_slack_seconds": SCHEDULE_SLACK_SECONDS,
        "production_max_seconds": PRODUCTION_MAX_SECONDS,
        "intended_production_bound_seconds": PRODUCTION_MAX_SECONDS,
        "time_compressed": True,
        "simulated_clock": False,
        "late_gap_seconds": LATE_GAP_SECONDS,
        "late_write_meets_cadence": False,
        "bound_gap_seconds": BOUND_GAP_SECONDS,
        "bound_gap_within_numeric_bound": passed,
        "hole": HOLE,
        "note": NOTE,
        "time_compressed_claimed_as_10_minute_cadence": False,
        "offline_exercise_claimed_as_condition_2": False,
        "stall_watchdog_claimed_as_cadence_writer": False,
        "crash_watchdog_claimed_as_cadence_writer": False,
        "pass_or_start_claimed": False,
        "refused_claims": _refused_claims(),
    }
    block.update(_closed_flags())
    return block


def scaffold_status_for_root(script_present: bool) -> dict[str, Any]:
    """Skip the exercise when the inspected root has no cadence writer."""
    if not script_present:
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    return stable_scaffold_status()


def stable_scaffold_status(*, force: bool = False) -> dict[str, Any]:
    """Deterministic report of the short exercise. No timings and no pids."""
    global _CACHE
    if _CACHE is not None and not force:
        return json.loads(json.dumps(_CACHE))
    if not SCRIPT.is_file():
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    measured = run_offline_exercise()
    if measured.get("ok") is True and measured.get("detail") == SUCCESS_DETAIL:
        block = _scaffold_shell(SUCCESS_DETAIL, ok=True, implementation_present=True)
        _CACHE = json.loads(json.dumps(block))
        return json.loads(json.dumps(block))
    return _scaffold_shell("exercise_failed", ok=False, implementation_present=False)


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


def annotate_scaffold_claim(block: dict[str, Any], claim: dict[str, Any] | None) -> None:
    """Record a pretense. Closed flags are applied again by the caller."""
    block["time_compressed_claimed_as_10_minute_cadence"] = False
    block["offline_exercise_claimed_as_condition_2"] = False
    block["stall_watchdog_claimed_as_cadence_writer"] = False
    block["crash_watchdog_claimed_as_cadence_writer"] = False
    block["pass_or_start_claimed"] = False
    if not isinstance(claim, dict):
        return
    if (
        claim.get("demonstrates_10_minute_supervision_cadence") is True
        or claim.get("time_compressed_exercise_demonstrates_10_minute_cadence") is True
        or claim.get("writes_on_schedule_demonstrate_10_minute_cadence") is True
        or claim.get("bound_gap_demonstrates_10_minute_supervision_cadence") is True
    ):
        block["time_compressed_claimed_as_10_minute_cadence"] = True
    if (
        claim.get("condition_2_satisfied") is True
        or claim.get("offline_exercise_satisfies_condition_2") is True
        or claim.get("time_compressed_exercise_satisfies_condition_2") is True
        or claim.get("implementation_satisfies_condition_2") is True
    ):
        block["offline_exercise_claimed_as_condition_2"] = True
    tool = str(claim.get("tool") or "")
    if claim.get("stall_watchdog_is_cadence_writer") is True or "stall_watchdog" in tool:
        block["stall_watchdog_claimed_as_cadence_writer"] = True
    if (
        claim.get("supervisor_watchdog_is_cadence_writer") is True
        or claim.get("crash_watchdog_is_cadence_writer") is True
        or "supervisor_watchdog" in tool
    ):
        block["crash_watchdog_claimed_as_cadence_writer"] = True
    if _claim_says_pass_or_start(claim):
        block["pass_or_start_claimed"] = True


def scaffold_violations(block: Any, *, require_success: bool = True) -> list[str]:
    """Reject a report that treats the short exercise as founder condition 2."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["supervision_cadence_writer"]
    for key, expected in _closed_flags().items():
        if block.get(key) != expected:
            if key in {
                "condition_2_satisfied",
                "offline_exercise_satisfies_condition_2",
                "time_compressed_exercise_satisfies_condition_2",
                "time_compressed_exercise_demonstrates_10_minute_cadence",
                "writes_on_schedule_demonstrate_10_minute_cadence",
                "bound_gap_demonstrates_10_minute_supervision_cadence",
                "demonstrates_10_minute_supervision_cadence",
                "dummy_tests_satisfy_condition_2",
                "scaffold_satisfies_condition_2",
                "implementation_satisfies_condition_2",
            }:
                violations.append("condition_2_unsatisfied")
            elif key in {
                "stall_watchdog_is_cadence_writer",
                "supervisor_watchdog_is_cadence_writer",
                "is_live_l2_2_supervisor",
                "is_supervisor_watchdog_of_live_supervisor",
                "is_live_l2_2_supervisor_watchdog",
                "live_supervisor_process",
                "live_soak_process",
            }:
                violations.append("supervision_cadence_writer")
            elif key in {"is_a_start", "binds_clock_start"}:
                violations.append("offline_probe_is_not_a_start")
            elif key == "can_start_clock":
                violations.append("forged_clock_start")
            elif key == "can_accept_l2_2":
                violations.append("forged_accept")
            elif key == "can_close_l2_2":
                violations.append("forged_close")
            elif key in {"implies_l2_2_pass", "l2_2_status"}:
                violations.append("forged_pass")
            elif key in {"a_72h_pass_is_production_readiness", "production_7x24", "implies_l2_2_acceptance"}:
                violations.append("production_claim")
            elif key in {"clock_state", "clock_effect"}:
                violations.append("clock_state")
            elif key in {"soak_launched", "documented_soak_argv_executed"}:
                violations.append("soak_launched")
            else:
                violations.append("supervision_cadence_writer")
    constants = {
        "tool": TOOL,
        "action": "time_compressed_offline_writes",
        "dut": "offline_exercise",
        "hole": HOLE,
        "note": NOTE,
        "exercise_interval_seconds": EXERCISE_INTERVAL_SECONDS,
        "exercise_write_count": EXERCISE_WRITE_COUNT,
        "schedule_slack_seconds": SCHEDULE_SLACK_SECONDS,
        "production_max_seconds": PRODUCTION_MAX_SECONDS,
        "intended_production_bound_seconds": PRODUCTION_MAX_SECONDS,
        "time_compressed": True,
        "simulated_clock": False,
        "late_gap_seconds": LATE_GAP_SECONDS,
        "late_write_meets_cadence": False,
        "bound_gap_seconds": BOUND_GAP_SECONDS,
        "bound_gap_demonstrates_10_minute_supervision_cadence": False,
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            violations.append("supervision_cadence_writer")
    for key in (
        "time_compressed_claimed_as_10_minute_cadence",
        "offline_exercise_claimed_as_condition_2",
        "stall_watchdog_claimed_as_cadence_writer",
        "crash_watchdog_claimed_as_cadence_writer",
        "pass_or_start_claimed",
    ):
        if not isinstance(block.get(key), bool):
            violations.append("supervision_cadence_writer")
    claims = block.get("refused_claims")
    expected_labels = [
        "time_compressed_called_10_minute_cadence",
        "offline_exercise_called_condition_2",
        "stall_watchdog_called_cadence_writer",
        "crash_watchdog_called_cadence_writer",
    ]
    if not isinstance(claims, list):
        violations.append("supervision_cadence_writer")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if labels != expected_labels:
            violations.append("supervision_cadence_writer")
        else:
            flags = (
                "time_compressed_claimed_as_10_minute_cadence",
                "offline_exercise_claimed_as_condition_2",
                "stall_watchdog_claimed_as_cadence_writer",
                "crash_watchdog_claimed_as_cadence_writer",
            )
            for item, flag in zip(claims, flags):
                if item.get(flag) is not True or item.get("condition_2_satisfied") is not False:
                    violations.append("condition_2_unsatisfied")
                if item.get("demonstrates_10_minute_supervision_cadence") is not False:
                    violations.append("condition_2_unsatisfied")
                if item.get("l2_2_status") != "NOT_STARTED" or item.get("can_start_clock") is not False:
                    violations.append("offline_probe_is_not_a_start")
    detail = block.get("detail")
    ok = block.get("ok")
    if require_success:
        if (
            ok is not True
            or detail != SUCCESS_DETAIL
            or block.get("implementation_present") is not True
            or block.get("writes_on_schedule_passed") is not True
            or block.get("bound_gap_within_numeric_bound") is not True
        ):
            violations.append("supervision_cadence_writer")
    else:
        if detail not in FAILURE_DETAILS or not isinstance(ok, bool):
            violations.append("supervision_cadence_writer")
        elif ok is True and (
            detail != SUCCESS_DETAIL
            or block.get("writes_on_schedule_passed") is not True
            or block.get("implementation_present") is not True
            or block.get("bound_gap_within_numeric_bound") is not True
        ):
            violations.append("supervision_cadence_writer")
        elif ok is not True and (
            block.get("writes_on_schedule_passed") is not False
            or block.get("implementation_present") is not False
            or block.get("bound_gap_within_numeric_bound") is not False
        ):
            violations.append("supervision_cadence_writer")
    return violations


def _summary(records: list[dict[str, Any]], *, interval: float, simulated: bool) -> dict[str, Any]:
    scheduled = writes_on_schedule(records, interval=interval, write_count=len(records))
    body: dict[str, Any] = {
        "ok": scheduled and len(records) >= 2,
        "detail": SUCCESS_DETAIL if scheduled and len(records) >= 2 else "exercise_failed",
        "tool": TOOL,
        "write_count": len(records),
        "configured_interval_seconds": interval,
        "production_max_seconds": PRODUCTION_MAX_SECONDS,
        "time_compressed": interval < PRODUCTION_MAX_SECONDS,
        "simulated_clock": simulated,
        "writes_on_schedule": scheduled,
        "note": NOTE,
    }
    body.update(_closed_flags())
    return body


def _error_summary(detail: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": False,
        "detail": detail,
        "tool": TOOL,
        "production_max_seconds": PRODUCTION_MAX_SECONDS,
        "time_compressed": True,
        "writes_on_schedule": False,
        "note": NOTE,
    }
    body.update(_closed_flags())
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, required=True)
    parser.add_argument("--writes", type=int, required=True)
    parser.add_argument("--max-runtime", type=float, default=8.0)
    parser.add_argument(
        "--simulated",
        action="store_true",
        help="advance a fake clock (still not a live 10-minute cadence)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    simulated = args.simulated is True
    clock: Clock | None = None
    sleep: Sleeper | None = None
    if simulated:
        state = {"now": 0.0}

        def clock() -> float:
            return state["now"]

        def sleep(seconds: float) -> None:
            state["now"] += float(seconds)

    try:
        records = emit_writes(
            args.out,
            interval=args.interval,
            writes=args.writes,
            simulated=simulated,
            clock=clock,
            sleep=sleep,
            max_runtime=None if simulated else args.max_runtime,
        )
    except ValueError as exc:
        print(json.dumps(_error_summary(str(exc)), ensure_ascii=False))
        return 2
    summary = _summary(records, interval=float(args.interval), simulated=simulated)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("ok") is True else 2


if __name__ == "__main__":
    sys.exit(main())
