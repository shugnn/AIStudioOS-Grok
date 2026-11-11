#!/usr/bin/env python3
"""Other-process watchdog for a supervisor pid.

Point this process at another pid. When that pid disappears, write a crash
record. The record is within 10 seconds when this process was polling the pid.

This is offline scaffolding. A dummy child, a short supervision_monitor.py the
caller spawned, and a crash record stamped 11 seconds later are not founder
condition 2. Condition 2 also needs a supervision write at least once every 10
minutes on a started L2-2 run. This script does not start that run, does not
launch soak_2h.py, and does not signal any process except the existence check
os.kill(pid, 0).

  python3 scripts/supervisor_watchdog.py --pid PID --record /tmp/crash.json --max-runtime 8
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = ROOT / "docs" / "progress"
SCRIPT = Path(__file__).resolve()
TOOL = "scripts/supervisor_watchdog.py"
CRASH_SCHEMA = "aistudioos-grok.supervisor-watchdog.crash.v1"
MAX_SECONDS = 10
SLOW_RECORD_SECONDS = 11
MAX_SCAFFOLD_RUNTIME = 60.0
MIN_POLL_SECONDS = 0.02
MAX_POLL_SECONDS = 1.0
SUCCESS_DETAIL = "implementation_exists_dummy_crash_within_10s_passed"
FAILURE_DETAILS = frozenset(
    {
        SUCCESS_DETAIL,
        "script_missing",
        "exercise_failed",
        "import_failed",
    }
)
NOTE = (
    "Implementation exists and dummy crash-within-10s tests passed. "
    "Dummy-process success is not a live L2-2 supervisor watchdog, "
    "does not demonstrate the 10-minute supervision write cadence, "
    "and does not satisfy founder condition 2."
)
CRASH_NOTE = "This crash record is not founder condition 2 and does not start L2-2."

_CACHE: dict[str, Any] | None = None


def _under_progress(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROGRESS.resolve())
    except (OSError, ValueError):
        return False
    return True


def pid_alive(pid: int) -> bool:
    """True when pid is a live process. Signal 0 does not kill. Zombies are gone."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        text = stat_path.read_text(encoding="utf-8")
    except OSError:
        return False
    end = text.rfind(")")
    if end < 0 or end + 2 >= len(text):
        return True
    return text[end + 2] != "Z"


def stop_owned_process(proc: subprocess.Popen[Any] | None) -> None:
    """Stop one Popen this caller created. Does not accept a raw pid."""
    if proc is None:
        return
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def record_latency_seconds(record: dict[str, Any]) -> float | None:
    for key in ("seconds_since_last_alive", "crash_recorded_within_seconds", "recorded_after_seconds"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        return float(value)
    return None


def deadline_met(
    *,
    latency: float | None,
    mtime_gap: float | None = None,
    max_seconds: float = MAX_SECONDS,
) -> bool:
    """True only when every present timing is inside the 10-second bound."""
    if latency is None and mtime_gap is None:
        return False
    if latency is not None and not (0 <= latency <= max_seconds):
        return False
    if mtime_gap is not None and not (0 <= mtime_gap <= max_seconds):
        return False
    return True


def record_meets_deadline(record: Any, *, max_seconds: float = MAX_SECONDS) -> bool:
    if not isinstance(record, dict):
        return False
    if "role" in record and record.get("role") != "other_process_crash_record":
        return False
    return deadline_met(latency=record_latency_seconds(record), max_seconds=max_seconds)


def assess_crash_record(record: Any, *, mtime_gap: float | None = None) -> dict[str, Any]:
    """Classify a record. A fast dummy record still does not satisfy condition 2."""
    latency = record_latency_seconds(record) if isinstance(record, dict) else None
    meets = deadline_met(latency=latency, mtime_gap=mtime_gap)
    return {
        "record_within_max_seconds": meets,
        "seconds_since_last_alive": latency,
        "mtime_gap_seconds": mtime_gap,
        "max_seconds": MAX_SECONDS,
        "condition_2_satisfied": False,
        "dummy_tests_satisfy_condition_2": False,
        "scaffold_satisfies_condition_2": False,
        "implementation_satisfies_condition_2": False,
        "is_live_l2_2_supervisor_watchdog": False,
        "demonstrates_10_minute_supervision_cadence": False,
        "is_a_start": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "soak_launched": False,
    }


def classify_mtime_gap(death: Path, record: Path, *, max_seconds: float = MAX_SECONDS) -> dict[str, Any]:
    """Compare two file mtimes. An 11-second gap does not meet the requirement."""
    try:
        gap = record.stat().st_mtime - death.stat().st_mtime
        body = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        assessed = assess_crash_record({}, mtime_gap=None)
        assessed["ok"] = False
        assessed["detail"] = "unreadable"
        return assessed
    if not isinstance(body, dict):
        body = {}
    assessed = assess_crash_record(body, mtime_gap=gap)
    assessed["ok"] = True
    assessed["detail"] = "mtime_gap"
    assessed["mtime_gap_seconds"] = gap
    assessed["record_within_max_seconds"] = deadline_met(
        latency=record_latency_seconds(body),
        mtime_gap=gap,
        max_seconds=max_seconds,
    )
    assessed["condition_2_satisfied"] = False
    return assessed


def _crash_payload(
    *,
    pid: int,
    role: str,
    seen_alive: bool,
    latency: float,
) -> dict[str, Any]:
    meets = deadline_met(latency=latency)
    return {
        "schema": CRASH_SCHEMA,
        "role": "other_process_crash_record",
        "watched_pid": pid,
        "watched_role": role,
        "event": "process_gone",
        "seen_alive": seen_alive,
        "seconds_since_last_alive": round(latency, 3),
        "max_seconds": MAX_SECONDS,
        "record_within_max_seconds": meets,
        "condition_2_satisfied": False,
        "dummy_tests_satisfy_condition_2": False,
        "scaffold_satisfies_condition_2": False,
        "is_live_l2_2_supervisor_watchdog": False,
        "demonstrates_10_minute_supervision_cadence": False,
        "is_a_start": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "soak_launched": False,
        "note": CRASH_NOTE,
    }


def _status_payload(*, pid: int, state: str, seen_alive: bool) -> dict[str, Any]:
    return {
        "role": "watch_status",
        "state": state,
        "watched_pid": pid,
        "seen_alive": seen_alive,
        "condition_2_satisfied": False,
        "is_live_l2_2_supervisor_watchdog": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "soak_launched": False,
    }


def watch_pid(
    pid: int,
    record_path: Path,
    *,
    poll_seconds: float = 0.05,
    max_runtime: float = 30.0,
    status_path: Path | None = None,
    role: str = "watched_process",
) -> dict[str, Any]:
    """Poll pid. Write a crash record only after it is gone. Never signals it to stop."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1 or pid == os.getpid():
        return {"ok": False, "code": 2, "detail": "pid_refused", "crash_record_written": False}
    if not (MIN_POLL_SECONDS <= poll_seconds <= MAX_POLL_SECONDS):
        return {"ok": False, "code": 2, "detail": "poll_refused", "crash_record_written": False}
    if not (0 < max_runtime <= MAX_SCAFFOLD_RUNTIME):
        return {"ok": False, "code": 2, "detail": "runtime_refused", "crash_record_written": False}
    if _under_progress(record_path) or (status_path is not None and _under_progress(status_path)):
        return {"ok": False, "code": 2, "detail": "repo_path_refused", "crash_record_written": False}
    if record_path.exists():
        return {"ok": False, "code": 2, "detail": "record_exists", "crash_record_written": False}
    if status_path is not None and status_path.resolve() == record_path.resolve():
        return {"ok": False, "code": 2, "detail": "status_is_record", "crash_record_written": False}

    started = time.monotonic()
    seen_alive = False
    last_alive: float | None = None
    while True:
        if pid_alive(pid):
            last_alive = time.monotonic()
            if not seen_alive:
                seen_alive = True
                if status_path is not None:
                    _write_json(status_path, _status_payload(pid=pid, state="watching", seen_alive=True))
            if (time.monotonic() - started) >= max_runtime:
                if status_path is not None:
                    _write_json(status_path, _status_payload(pid=pid, state="still_alive", seen_alive=True))
                return {
                    "ok": True,
                    "code": 0,
                    "detail": "still_alive",
                    "crash_record_written": False,
                    "seen_alive": True,
                }
            time.sleep(poll_seconds)
            continue
        anchor = last_alive if last_alive is not None else started
        latency = time.monotonic() - anchor
        payload = _crash_payload(pid=pid, role=role, seen_alive=seen_alive, latency=latency)
        _write_json(record_path, payload)
        meets = payload["record_within_max_seconds"] is True
        return {
            "ok": meets,
            "code": 1 if meets else 2,
            "detail": "crash_recorded" if meets else "crash_record_too_slow",
            "crash_record_written": True,
            "seen_alive": seen_alive,
            "seconds_since_last_alive": payload["seconds_since_last_alive"],
            "record_within_max_seconds": meets,
            "condition_2_satisfied": False,
        }


def _spawn_sleeper(seconds: float = 30.0) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_watch(
    pid: int,
    record: Path,
    *,
    status: Path | None,
    max_runtime: float,
    poll_seconds: float,
    role: str,
) -> subprocess.Popen[Any]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--pid",
        str(pid),
        "--record",
        str(record),
        "--poll-seconds",
        str(poll_seconds),
        "--max-runtime",
        str(max_runtime),
        "--role",
        role,
    ]
    if status is not None:
        cmd.extend(["--status", str(status)])
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_status(path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                doc = None
            if isinstance(doc, dict) and doc.get("seen_alive") is True and doc.get("role") == "watch_status":
                return True
        time.sleep(0.02)
    return False


def _wait_record(path: Path, timeout: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                doc = None
            if isinstance(doc, dict) and doc.get("role") == "other_process_crash_record":
                return doc
        time.sleep(0.02)
    return None


def run_dummy_exercise() -> dict[str, Any]:
    """Spawn short-lived dummies and a watchdog subprocess. Does not touch host pids.

    The returned dict may contain timings. Callers that commit a report use
    stable_scaffold_status, which drops those timings.
    """
    crash_doc: dict[str, Any] | None = None
    alive_clean = False
    slow_rejected = False
    try:
        with tempfile.TemporaryDirectory(prefix="supervisor_watchdog_") as tmp_name:
            tmp = Path(tmp_name)
            if _under_progress(tmp):
                return {"ok": False, "detail": "exercise_failed"}
            dummy = _spawn_sleeper()
            watch: subprocess.Popen[Any] | None = None
            try:
                record = tmp / "crash.json"
                status = tmp / "status.json"
                watch = _spawn_watch(
                    dummy.pid,
                    record,
                    status=status,
                    max_runtime=8,
                    poll_seconds=0.05,
                    role="dummy",
                )
                if not _wait_status(status, 3):
                    return {"ok": False, "detail": "exercise_failed"}
                stop_owned_process(dummy)
                crash_doc = _wait_record(record, 10)
            finally:
                stop_owned_process(dummy)
                stop_owned_process(watch)
            if not isinstance(crash_doc, dict):
                return {"ok": False, "detail": "exercise_failed"}
            latency = record_latency_seconds(crash_doc)
            if (
                crash_doc.get("record_within_max_seconds") is not True
                or latency is None
                or latency > MAX_SECONDS
                or crash_doc.get("condition_2_satisfied") is not False
                or crash_doc.get("watched_role") != "dummy"
            ):
                return {"ok": False, "detail": "exercise_failed"}

            alive = _spawn_sleeper()
            alive_watch: subprocess.Popen[Any] | None = None
            try:
                alive_record = tmp / "alive_crash.json"
                alive_watch = _spawn_watch(
                    alive.pid,
                    alive_record,
                    status=None,
                    max_runtime=0.4,
                    poll_seconds=0.05,
                    role="dummy",
                )
                try:
                    alive_watch.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    return {"ok": False, "detail": "exercise_failed"}
                alive_clean = alive.poll() is None and not alive_record.exists() and alive_watch.returncode == 0
            finally:
                stop_owned_process(alive)
                stop_owned_process(alive_watch)
            if not alive_clean:
                return {"ok": False, "detail": "exercise_failed"}

            death = tmp / "death.json"
            slow = tmp / "slow.json"
            death.write_text('{"role":"death"}\n', encoding="utf-8")
            slow_body = {
                "role": "other_process_crash_record",
                "seconds_since_last_alive": SLOW_RECORD_SECONDS,
                "condition_2_satisfied": False,
            }
            slow.write_text(json.dumps(slow_body), encoding="utf-8")
            now = time.time()
            os.utime(death, (now - 30, now - 30))
            os.utime(slow, (now - 30 + SLOW_RECORD_SECONDS, now - 30 + SLOW_RECORD_SECONDS))
            classified = classify_mtime_gap(death, slow)
            slow_rejected = (
                classified.get("record_within_max_seconds") is False
                and classified.get("condition_2_satisfied") is False
                and record_meets_deadline(slow_body) is False
            )
    except OSError:
        return {"ok": False, "detail": "exercise_failed"}
    if not slow_rejected:
        return {"ok": False, "detail": "exercise_failed"}
    return {
        "ok": True,
        "detail": SUCCESS_DETAIL,
        "dummy_crash_within_10s_passed": True,
        "dummy_still_alive_wrote_no_crash_record": True,
        "record_11s_later_meets_requirement": False,
    }


def _closed_flags() -> dict[str, Any]:
    return {
        "condition_2_satisfied": False,
        "dummy_tests_satisfy_condition_2": False,
        "scaffold_satisfies_condition_2": False,
        "implementation_satisfies_condition_2": False,
        "synthetic_probe_satisfies_condition_2": False,
        "stall_watchdog_satisfies_condition_2": False,
        "offline_probe_satisfies_condition_2": False,
        "offline_probe_is_supervisor_watchdog": False,
        "stall_watchdog_is_supervisor_watchdog": False,
        "is_live_l2_2_supervisor_watchdog": False,
        "is_supervisor_watchdog_of_live_supervisor": False,
        "demonstrates_10_minute_supervision_cadence": False,
        "live_supervisor_process": False,
        "live_soak_process": False,
        "live_watchdog_process": False,
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


def _refused_claims() -> list[dict[str, Any]]:
    common = _closed_flags()
    specs = (
        ("dummy_scaffold_called_condition_2", "dummy_scaffold_claimed_as_condition_2"),
        ("synthetic_probe_called_condition_2", "synthetic_probe_claimed_as_condition_2"),
        ("stall_watchdog_called_condition_2", "stall_watchdog_claimed_as_condition_2"),
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
        "action": "dummy_process_watch",
        "dut": "test_spawned_dummy",
        "detail": detail,
        "implementation_present": implementation_present and passed,
        "dummy_crash_within_10s_passed": passed,
        "dummy_still_alive_wrote_no_crash_record": passed,
        "record_11s_later_meets_requirement": False,
        "slow_record_seconds": SLOW_RECORD_SECONDS,
        "supervisor_watchdog_max_seconds": MAX_SECONDS,
        "hole": "dummy_exercise_is_not_a_live_l2_2_supervisor_watchdog",
        "note": NOTE,
        "dummy_scaffold_claimed_as_condition_2": False,
        "synthetic_probe_claimed_as_condition_2": False,
        "stall_watchdog_claimed_as_condition_2": False,
        "pass_or_start_claimed": False,
        "refused_claims": _refused_claims(),
    }
    block.update(_closed_flags())
    return block


def scaffold_status_for_root(script_present: bool) -> dict[str, Any]:
    """Skip the exercise when the inspected root has no watchdog script."""
    if not script_present:
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    return stable_scaffold_status()


def stable_scaffold_status(*, force: bool = False) -> dict[str, Any]:
    """Deterministic report of the dummy exercise. No pids and no timings."""
    global _CACHE
    if _CACHE is not None and not force:
        return json.loads(json.dumps(_CACHE))
    if not SCRIPT.is_file():
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    measured = run_dummy_exercise()
    if measured.get("ok") is True and measured.get("detail") == SUCCESS_DETAIL:
        block = _scaffold_shell(SUCCESS_DETAIL, ok=True, implementation_present=True)
        _CACHE = json.loads(json.dumps(block))
        return json.loads(json.dumps(block))
    return _scaffold_shell("exercise_failed", ok=False, implementation_present=False)


def apply_closed_flags(block: dict[str, Any]) -> dict[str, Any]:
    """Force the honesty flags. A claim cannot open them."""
    block.update(_closed_flags())
    return block


def annotate_scaffold_claim(block: dict[str, Any], claim: dict[str, Any] | None) -> None:
    """Record a pretense. Closed flags are applied again by the caller."""
    block["dummy_scaffold_claimed_as_condition_2"] = False
    block["synthetic_probe_claimed_as_condition_2"] = False
    block["stall_watchdog_claimed_as_condition_2"] = False
    block["pass_or_start_claimed"] = False
    if not isinstance(claim, dict):
        return
    if (
        claim.get("dummy_tests_satisfy_condition_2") is True
        or claim.get("scaffold_satisfies_condition_2") is True
        or claim.get("implementation_satisfies_condition_2") is True
        or claim.get("dummy_crash_within_10s_satisfies_condition_2") is True
        or claim.get("condition_2_satisfied") is True
    ):
        block["dummy_scaffold_claimed_as_condition_2"] = True
    if (
        claim.get("synthetic_probe_satisfies_condition_2") is True
        or claim.get("offline_probe_satisfies_condition_2") is True
        or claim.get("offline_probe_is_supervisor_watchdog") is True
    ):
        block["synthetic_probe_claimed_as_condition_2"] = True
    tool = str(claim.get("tool") or "")
    if (
        claim.get("stall_watchdog_satisfies_condition_2") is True
        or claim.get("stall_watchdog_is_supervisor_watchdog") is True
        or "stall_watchdog" in tool
    ):
        block["stall_watchdog_claimed_as_condition_2"] = True
    status = str(claim.get("l2_2_status") or "").strip().upper().replace(" ", "_")
    clock = str(claim.get("clock_state") or "").strip().upper().replace(" ", "_")
    production = str(claim.get("production_7x24") or "").strip().upper().replace(" ", "_")
    if (
        status in {"PASS", "ACCEPTED", "STARTED"}
        or status.startswith("PASS")
        or clock in {"STARTED", "WALL_OBSERVED"}
        or production in {"ACCEPTED", "PASS"}
        or "ACCEPTED" in production
        or claim.get("can_start_clock") is True
        or claim.get("is_a_start") is True
    ):
        block["pass_or_start_claimed"] = True


def scaffold_violations(block: Any, *, require_success: bool = True) -> list[str]:
    """Reject a report that treats the dummy scaffold as founder condition 2."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["supervisor_watchdog_implementation"]
    for key, expected in _closed_flags().items():
        if block.get(key) != expected:
            if key in {
                "condition_2_satisfied",
                "dummy_tests_satisfy_condition_2",
                "scaffold_satisfies_condition_2",
                "implementation_satisfies_condition_2",
                "synthetic_probe_satisfies_condition_2",
                "stall_watchdog_satisfies_condition_2",
                "offline_probe_satisfies_condition_2",
                "demonstrates_10_minute_supervision_cadence",
            }:
                violations.append("condition_2_unsatisfied")
            elif key in {
                "offline_probe_is_supervisor_watchdog",
                "stall_watchdog_is_supervisor_watchdog",
                "is_live_l2_2_supervisor_watchdog",
                "is_supervisor_watchdog_of_live_supervisor",
                "live_supervisor_process",
                "live_soak_process",
                "live_watchdog_process",
            }:
                violations.append("offline_probe_is_not_supervisor_watchdog")
            elif key in {"is_a_start", "binds_clock_start"}:
                violations.append("offline_probe_is_not_a_start")
            elif key in {"can_start_clock"}:
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
                violations.append("supervisor_watchdog_implementation")
    constants = {
        "tool": TOOL,
        "action": "dummy_process_watch",
        "dut": "test_spawned_dummy",
        "hole": "dummy_exercise_is_not_a_live_l2_2_supervisor_watchdog",
        "note": NOTE,
        "slow_record_seconds": SLOW_RECORD_SECONDS,
        "supervisor_watchdog_max_seconds": MAX_SECONDS,
        "record_11s_later_meets_requirement": False,
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            violations.append("supervisor_watchdog_implementation")
    for key in (
        "dummy_scaffold_claimed_as_condition_2",
        "synthetic_probe_claimed_as_condition_2",
        "stall_watchdog_claimed_as_condition_2",
        "pass_or_start_claimed",
    ):
        if not isinstance(block.get(key), bool):
            violations.append("supervisor_watchdog_implementation")
    claims = block.get("refused_claims")
    expected_labels = [
        "dummy_scaffold_called_condition_2",
        "synthetic_probe_called_condition_2",
        "stall_watchdog_called_condition_2",
    ]
    if not isinstance(claims, list):
        violations.append("supervisor_watchdog_implementation")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if labels != expected_labels:
            violations.append("supervisor_watchdog_implementation")
        else:
            flags = (
                "dummy_scaffold_claimed_as_condition_2",
                "synthetic_probe_claimed_as_condition_2",
                "stall_watchdog_claimed_as_condition_2",
            )
            for item, flag in zip(claims, flags):
                if item.get(flag) is not True or item.get("condition_2_satisfied") is not False:
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
            or block.get("dummy_crash_within_10s_passed") is not True
            or block.get("dummy_still_alive_wrote_no_crash_record") is not True
        ):
            violations.append("supervisor_watchdog_implementation")
    else:
        if detail not in FAILURE_DETAILS or not isinstance(ok, bool):
            violations.append("supervisor_watchdog_implementation")
        elif ok is True and (
            detail != SUCCESS_DETAIL
            or block.get("dummy_crash_within_10s_passed") is not True
            or block.get("implementation_present") is not True
        ):
            violations.append("supervisor_watchdog_implementation")
        elif ok is not True and (
            block.get("dummy_crash_within_10s_passed") is not False
            or block.get("implementation_present") is not False
            or block.get("dummy_still_alive_wrote_no_crash_record") is not False
        ):
            violations.append("supervisor_watchdog_implementation")
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--status", type=Path, default=None)
    parser.add_argument("--poll-seconds", type=float, default=0.05)
    parser.add_argument("--max-runtime", type=float, default=30.0)
    parser.add_argument("--role", default="watched_process")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = watch_pid(
        args.pid,
        args.record,
        poll_seconds=args.poll_seconds,
        max_runtime=args.max_runtime,
        status_path=args.status,
        role=args.role,
    )
    print(json.dumps(result, ensure_ascii=False))
    code = result.get("code")
    return code if isinstance(code, int) else 2


if __name__ == "__main__":
    raise SystemExit(main())
