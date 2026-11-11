"""Offline supervisor watchdog. Dummy processes only. Not founder condition 2."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import supervisor_watchdog as wd  # noqa: E402

PROGRESS = ROOT / "docs" / "progress"
RUNTIME = (
    PROGRESS / "EMERGENCY_STOP",
    PROGRESS / "STALL_ALERT.json",
    PROGRESS / "coverage_gaps.jsonl",
)


def _spawn_sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop(proc: subprocess.Popen[bytes] | None) -> None:
    wd.stop_owned_process(proc)


def _watch(
    pid: int,
    record: Path,
    *,
    status: Path | None,
    max_runtime: float,
    role: str,
) -> subprocess.Popen[bytes]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "supervisor_watchdog.py"),
        "--pid",
        str(pid),
        "--record",
        str(record),
        "--poll-seconds",
        "0.05",
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


def _wait_seen(status: Path, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if status.is_file():
            try:
                doc = json.loads(status.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                doc = None
            if isinstance(doc, dict) and doc.get("seen_alive") is True:
                return True
        time.sleep(0.02)
    return False


def _wait_crash(record: Path, timeout: float = 10.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if record.is_file():
            try:
                doc = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                doc = None
            if isinstance(doc, dict):
                return doc
        time.sleep(0.02)
    return None


def test_killed_dummy_writes_a_crash_record_within_10_seconds(tmp_path: Path):
    before = {path: path.exists() for path in RUNTIME}
    dummy = _spawn_sleeper()
    watch = None
    try:
        record = tmp_path / "crash.json"
        status = tmp_path / "status.json"
        watch = _watch(dummy.pid, record, status=status, max_runtime=8, role="dummy")
        assert _wait_seen(status)
        killed_at = time.monotonic()
        _stop(dummy)
        doc = _wait_crash(record)
        elapsed = time.monotonic() - killed_at
        assert doc is not None
        assert elapsed <= wd.MAX_SECONDS
        assert elapsed < 3
        assert doc["role"] == "other_process_crash_record"
        assert doc["watched_pid"] == dummy.pid
        assert doc["watched_role"] == "dummy"
        assert doc["event"] == "process_gone"
        assert doc["seen_alive"] is True
        assert doc["record_within_max_seconds"] is True
        assert doc["seconds_since_last_alive"] <= wd.MAX_SECONDS
        assert doc["seconds_since_last_alive"] < 3
        assert doc["condition_2_satisfied"] is False
        assert doc["dummy_tests_satisfy_condition_2"] is False
        assert doc["is_live_l2_2_supervisor_watchdog"] is False
        assert doc["demonstrates_10_minute_supervision_cadence"] is False
        assert doc["l2_2_status"] == "NOT_STARTED"
        assert doc["clock_state"] == "NOT_STARTED"
        assert doc["production_7x24"] == "NOT_ACCEPTED"
        assert doc["can_start_clock"] is False
        assert doc["soak_launched"] is False
        assert wd.record_meets_deadline(doc) is True
        assessed = wd.assess_crash_record(doc)
        assert assessed["record_within_max_seconds"] is True
        assert assessed["condition_2_satisfied"] is False
    finally:
        _stop(dummy)
        _stop(watch)
    after = {path: path.exists() for path in RUNTIME}
    assert after == before


def test_live_dummy_does_not_get_a_crash_record(tmp_path: Path):
    dummy = _spawn_sleeper()
    watch = None
    try:
        record = tmp_path / "crash.json"
        watch = _watch(dummy.pid, record, status=None, max_runtime=0.4, role="dummy")
        assert watch.wait(timeout=3) == 0
        assert dummy.poll() is None
        assert not record.exists()
    finally:
        _stop(dummy)
        _stop(watch)


def test_crash_record_11_seconds_later_does_not_meet_the_requirement(tmp_path: Path):
    slow = {
        "role": "other_process_crash_record",
        "seconds_since_last_alive": 11,
        "record_within_max_seconds": True,
        "condition_2_satisfied": True,
    }
    assert wd.record_meets_deadline(slow) is False
    assessed = wd.assess_crash_record(slow)
    assert assessed["record_within_max_seconds"] is False
    assert assessed["condition_2_satisfied"] is False
    assert assessed["dummy_tests_satisfy_condition_2"] is False
    assert assessed["is_live_l2_2_supervisor_watchdog"] is False
    assert assessed["l2_2_status"] == "NOT_STARTED"
    assert assessed["can_start_clock"] is False

    fast = {
        "role": "other_process_crash_record",
        "seconds_since_last_alive": 0.2,
        "condition_2_satisfied": True,
    }
    assert wd.record_meets_deadline(fast) is True
    fast_assessed = wd.assess_crash_record(fast)
    assert fast_assessed["record_within_max_seconds"] is True
    assert fast_assessed["condition_2_satisfied"] is False

    death = tmp_path / "death.json"
    record = tmp_path / "slow.json"
    death.write_text('{"role":"death"}\n', encoding="utf-8")
    record.write_text(json.dumps(slow), encoding="utf-8")
    now = time.time()
    os.utime(death, (now - 30, now - 30))
    os.utime(record, (now - 19, now - 19))
    classified = wd.classify_mtime_gap(death, record)
    assert classified["record_within_max_seconds"] is False
    assert classified["condition_2_satisfied"] is False
    assert classified["mtime_gap_seconds"] == pytest.approx(11, abs=0.05)


def test_watchdog_can_record_a_spawned_supervision_monitor_exit(tmp_path: Path):
    summary = tmp_path / "summary.jsonl"
    gap = tmp_path / "gaps.jsonl"
    summary.write_text('{"utc":"2026-02-01T00:00:00Z","synthetic":true}\n', encoding="utf-8")
    before = {path: path.exists() for path in RUNTIME}
    monitor = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "supervision_monitor.py"),
            "--summary",
            str(summary),
            "--gap-log",
            str(gap),
            "--interval",
            "0.5",
            "--max-runtime",
            "20",
            "--never-red",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    watch = None
    try:
        record = tmp_path / "crash.json"
        status = tmp_path / "status.json"
        watch = _watch(monitor.pid, record, status=status, max_runtime=8, role="supervision_monitor")
        assert _wait_seen(status)
        assert monitor.poll() is None
        killed_at = time.monotonic()
        _stop(monitor)
        doc = _wait_crash(record)
        assert doc is not None
        assert time.monotonic() - killed_at <= wd.MAX_SECONDS
        assert doc["watched_pid"] == monitor.pid
        assert doc["watched_role"] == "supervision_monitor"
        assert doc["record_within_max_seconds"] is True
        assert doc["seconds_since_last_alive"] <= wd.MAX_SECONDS
        assert doc["condition_2_satisfied"] is False
        assert doc["is_live_l2_2_supervisor_watchdog"] is False
        assert doc["soak_launched"] is False
    finally:
        _stop(monitor)
        _stop(watch)
    assert {path: path.exists() for path in RUNTIME} == before


def test_scaffold_status_records_dummy_success_without_satisfying_condition_2():
    block = wd.stable_scaffold_status()
    assert block["ok"] is True
    assert block["detail"] == wd.SUCCESS_DETAIL
    assert block["tool"] == "scripts/supervisor_watchdog.py"
    assert block["implementation_present"] is True
    assert block["dummy_crash_within_10s_passed"] is True
    assert block["dummy_still_alive_wrote_no_crash_record"] is True
    assert block["record_11s_later_meets_requirement"] is False
    assert block["condition_2_satisfied"] is False
    assert block["dummy_tests_satisfy_condition_2"] is False
    assert block["scaffold_satisfies_condition_2"] is False
    assert block["implementation_satisfies_condition_2"] is False
    assert block["synthetic_probe_satisfies_condition_2"] is False
    assert block["stall_watchdog_satisfies_condition_2"] is False
    assert block["is_live_l2_2_supervisor_watchdog"] is False
    assert block["demonstrates_10_minute_supervision_cadence"] is False
    assert block["live_supervisor_process"] is False
    assert block["live_watchdog_process"] is False
    assert block["soak_launched"] is False
    assert block["can_start_clock"] is False
    assert block["can_accept_l2_2"] is False
    assert block["can_close_l2_2"] is False
    assert block["l2_2_status"] == "NOT_STARTED"
    assert block["clock_state"] == "NOT_STARTED"
    assert block["production_7x24"] == "NOT_ACCEPTED"
    assert wd.scaffold_violations(block) == []
    claimed = json.loads(json.dumps(block))
    wd.annotate_scaffold_claim(
        claimed,
        {
            "dummy_tests_satisfy_condition_2": True,
            "condition_2_satisfied": True,
            "l2_2_status": "PASS",
            "clock_state": "STARTED",
            "production_7x24": "ACCEPTED",
            "can_start_clock": True,
        },
    )
    wd.apply_closed_flags(claimed)
    assert claimed["dummy_scaffold_claimed_as_condition_2"] is True
    assert claimed["pass_or_start_claimed"] is True
    assert claimed["condition_2_satisfied"] is False
    assert claimed["dummy_tests_satisfy_condition_2"] is False
    assert claimed["l2_2_status"] == "NOT_STARTED"
    assert claimed["can_start_clock"] is False
    assert wd.scaffold_violations(claimed) == []
