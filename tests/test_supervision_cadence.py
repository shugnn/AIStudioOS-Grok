"""Offline supervision cadence writer. Short interval only. Not founder condition 2."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import supervision_cadence as cadence  # noqa: E402

PROGRESS = ROOT / "docs" / "progress"
RUNTIME = (
    PROGRESS / "EMERGENCY_STOP",
    PROGRESS / "STALL_ALERT.json",
    PROGRESS / "coverage_gaps.jsonl",
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += float(seconds)


def _honesty(doc: dict) -> None:
    assert doc["condition_2_satisfied"] is False
    assert doc["demonstrates_10_minute_supervision_cadence"] is False
    assert doc["is_supervisor_watchdog_of_live_supervisor"] is False
    assert doc["can_start_clock"] is False
    assert doc["can_accept_l2_2"] is False
    assert doc["can_close_l2_2"] is False
    assert doc["l2_2_status"] == "NOT_STARTED"
    assert doc["clock_state"] == "NOT_STARTED"
    assert doc["production_7x24"] == "NOT_ACCEPTED"
    assert doc["soak_launched"] is False
    assert doc["is_a_start"] is False


def test_short_interval_writes_land_on_schedule(tmp_path: Path):
    before = {path: path.exists() for path in RUNTIME}
    out = tmp_path / "writes.jsonl"
    started = time.monotonic()
    records = cadence.emit_writes(
        out,
        interval=cadence.EXERCISE_INTERVAL_SECONDS,
        writes=cadence.EXERCISE_WRITE_COUNT,
        max_runtime=8,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 3
    assert cadence.writes_on_schedule(
        records,
        interval=cadence.EXERCISE_INTERVAL_SECONDS,
        write_count=cadence.EXERCISE_WRITE_COUNT,
    )
    assert [row["sequence"] for row in records] == [1, 2, 3]
    assert records[0]["gap_seconds"] == 0
    for row in records[1:]:
        assert cadence.EXERCISE_INTERVAL_SECONDS - 0.05 <= row["gap_seconds"] <= cadence.EXERCISE_INTERVAL_SECONDS + 2
        assert row["gap_within_production_bound"] is True
        assert row["on_configured_schedule"] is True
        assert row["time_compressed"] is True
        assert row["simulated_clock"] is False
        _honesty(row)
    assert records[0]["time_compressed"] is True
    _honesty(records[0])
    assert cadence.read_writes(out) == records
    after = {path: path.exists() for path in RUNTIME}
    assert after == before


def test_cli_short_exercise_keeps_honesty_flags(tmp_path: Path):
    out = tmp_path / "cli.jsonl"
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "supervision_cadence.py"),
            "--out",
            str(out),
            "--interval",
            "0.2",
            "--writes",
            "3",
            "--max-runtime",
            "8",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["ok"] is True
    assert summary["writes_on_schedule"] is True
    assert summary["time_compressed"] is True
    assert summary["simulated_clock"] is False
    assert summary["production_max_seconds"] == 600
    _honesty(summary)
    rows = cadence.read_writes(out)
    assert cadence.writes_on_schedule(rows, interval=0.2, write_count=3)


def test_late_gap_does_not_meet_the_cadence_and_the_bound_does_not_open_flags():
    late = cadence.assess_gap(601)
    assert late["meets_cadence_bound"] is False
    assert late["write_later_than_bound"] is True
    assert late["late_write_meets_cadence"] is False
    _honesty(late)
    over = cadence.assess_gap(660)
    assert over["meets_cadence_bound"] is False
    assert over["late_write_meets_cadence"] is False
    bound = cadence.assess_gap(600)
    assert bound["meets_cadence_bound"] is True
    assert bound["write_later_than_bound"] is False
    assert bound["late_write_meets_cadence"] is False
    _honesty(bound)
    claimed = cadence.assess_gap(600, live_started=True)
    assert claimed["meets_cadence_bound"] is True
    assert claimed["live_started_claimed"] is True
    assert claimed["pass_or_start_claimed"] is True
    _honesty(claimed)
    assert cadence.gap_within_bound(-1) is False
    assert cadence.gap_within_bound(True) is False
    assert cadence.interval_allowed(601) is False
    assert cadence.interval_allowed(600) is True
    assert cadence.interval_allowed(0) is False


def test_simulated_production_interval_stays_offline(tmp_path: Path):
    clock = _FakeClock()
    out = tmp_path / "simulated.jsonl"
    records = cadence.emit_writes(
        out,
        interval=600,
        writes=3,
        simulated=True,
        clock=clock.clock,
        sleep=clock.sleep,
    )
    assert [row["gap_seconds"] for row in records] == [0, 600, 600]
    assert all(row["gap_within_production_bound"] is True for row in records)
    assert all(row["time_compressed"] is False for row in records)
    assert all(row["simulated_clock"] is True for row in records)
    for row in records:
        _honesty(row)
    assert cadence.writes_on_schedule(records, interval=600, write_count=3)
    assert abs(clock.now - 1200) < 0.001


def test_real_sleep_refuses_a_span_past_the_scaffold_cap(tmp_path: Path):
    called = {"sleep": 0}

    def boom(seconds: float) -> None:
        called["sleep"] += 1
        raise AssertionError("slept")

    with pytest.raises(ValueError, match="planned_duration_refused"):
        cadence.emit_writes(
            tmp_path / "long.jsonl",
            interval=20,
            writes=3,
            simulated=False,
            sleep=boom,
        )
    assert called["sleep"] == 0
    assert not (tmp_path / "long.jsonl").exists()


def test_progress_directory_is_not_a_write_target():
    target = PROGRESS / "l2_2" / "scaffold" / "cadence_writes.jsonl"
    with pytest.raises(ValueError, match="refusing_progress_write"):
        cadence.emit_writes(target, interval=0.2, writes=2, simulated=True, clock=lambda: 0.0, sleep=lambda _s: None)
    assert not target.exists()


def test_stable_scaffold_records_the_short_exercise_without_opening_flags():
    block = cadence.stable_scaffold_status()
    assert cadence.scaffold_violations(block, require_success=True) == []
    assert block["ok"] is True
    assert block["detail"] == cadence.SUCCESS_DETAIL
    assert block["writes_on_schedule_passed"] is True
    assert block["exercise_interval_seconds"] == 0.2
    assert block["production_max_seconds"] == 600
    assert block["time_compressed"] is True
    assert block["simulated_clock"] is False
    assert block["late_gap_seconds"] == 601
    assert block["late_write_meets_cadence"] is False
    assert block["bound_gap_seconds"] == 600
    assert block["bound_gap_within_numeric_bound"] is True
    assert block["hole"] == cadence.HOLE
    _honesty(block)
    labels = [item["label"] for item in block["refused_claims"]]
    assert labels == [
        "time_compressed_called_10_minute_cadence",
        "offline_exercise_called_condition_2",
        "stall_watchdog_called_cadence_writer",
        "crash_watchdog_called_cadence_writer",
    ]
    for item in block["refused_claims"]:
        _honesty(item)


def test_forged_cadence_claim_stays_closed():
    block = cadence.stable_scaffold_status()
    cadence.annotate_scaffold_claim(
        block,
        {
            "demonstrates_10_minute_supervision_cadence": True,
            "condition_2_satisfied": True,
            "tool": "scripts/stall_watchdog.py",
            "l2_2_status": "PASS",
            "clock_state": "STARTED",
            "can_start_clock": True,
            "production_7x24": "ACCEPTED",
        },
    )
    cadence.apply_closed_flags(block)
    assert block["time_compressed_claimed_as_10_minute_cadence"] is True
    assert block["offline_exercise_claimed_as_condition_2"] is True
    assert block["stall_watchdog_claimed_as_cadence_writer"] is True
    assert block["pass_or_start_claimed"] is True
    _honesty(block)
    assert cadence.scaffold_violations(block, require_success=True) == []
    missing = cadence.scaffold_status_for_root(False)
    assert missing["ok"] is False
    assert missing["detail"] == "script_missing"
    assert missing["writes_on_schedule_passed"] is False
    assert missing["demonstrates_10_minute_supervision_cadence"] is False
    assert cadence.scaffold_violations(missing, require_success=False) == []
