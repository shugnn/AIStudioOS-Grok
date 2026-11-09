"""Yellow-gap logger. A line is not a soak, not a 72h start, and not acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_gap_log as gaps  # noqa: E402
import l2_2_score as l2  # noqa: E402
import supervision_monitor as mon  # noqa: E402


def test_bands_match_r2_thresholds():
    assert gaps.classify_band(12.9) == "ok"
    assert gaps.classify_band(13) == "yellow"
    assert gaps.classify_band(300) == "yellow"
    assert gaps.classify_band(300.1) == "red"
    with pytest.raises(gaps.GapLogError):
        gaps.classify_band(-1)
    with pytest.raises(gaps.GapLogError):
        gaps.classify_band(True)  # type: ignore[arg-type]


def test_append_is_gap_only_and_cannot_complete_a_soak(tmp_path: Path):
    path = tmp_path / "coverage_gaps.jsonl"
    yellow = gaps.build_record(
        gap_seconds=30,
        source="operator_sample",
        timestamp="2026-02-01T00:00:30Z",
        mono_seconds=30,
    )
    red = gaps.build_record(
        gap_seconds=301,
        source="soak_summary_path",
        timestamp="2026-02-01T00:06:00Z",
        mono_seconds=360,
    )
    gaps.append_record(path, yellow)
    gaps.append_record(path, red)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["band"] for row in rows] == ["yellow", "red"]
    for row in rows:
        assert set(("timestamp", "gap_seconds", "band", "source")).issubset(row)
        assert row["implies_soak_complete"] is False
        assert row["clock_effect"] == "none"
        assert "can_accept_l2_2" not in row
        assert "can_start_clock" not in row
        assert row["schema"] == gaps.SCHEMA
        assert row.get("l2_2_status") != "PASS"
    assert rows[0]["coverage_gap"] is True
    assert rows[1]["coverage_gap"] is False
    assert rows[0]["timestamp"] == "2026-02-01T00:00:30Z"


def test_ok_is_logged_only_when_a_gap_recovers(tmp_path: Path):
    assert gaps.should_append("ok", None) is False
    assert gaps.should_append("yellow", None) is True
    assert gaps.should_append("ok", "yellow") is True
    path = tmp_path / "gaps.jsonl"
    common = {"source": "operator_sample", "mono_seconds": 1.0}
    mon.observe(
        age_seconds=5,
        signal="present",
        previous_band=None,
        timestamp="2026-02-01T00:00:05Z",
        log_path=path,
        **common,
    )
    mon.observe(
        age_seconds=30,
        signal="present",
        previous_band="ok",
        timestamp="2026-02-01T00:00:30Z",
        log_path=path,
        **common,
    )
    recovered = mon.observe(
        age_seconds=2,
        signal="present",
        previous_band="yellow",
        timestamp="2026-02-01T00:00:40Z",
        log_path=path,
        **common,
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["band"] for row in rows] == ["yellow", "ok"]
    assert recovered["appended"] is True
    assert recovered["red_exit"] is False
    assert rows[1]["implies_soak_complete"] is False


def test_five_minutes_is_yellow_and_a_missing_signal_is_red(tmp_path: Path):
    path = tmp_path / "gaps.jsonl"
    held = mon.observe(
        age_seconds=300,
        signal="present",
        previous_band=None,
        source="soak_summary_path",
        timestamp="2026-02-01T00:05:00Z",
        mono_seconds=300,
        log_path=path,
    )
    assert held["band"] == "yellow"
    assert held["red_exit"] is False
    assert held["record"]["coverage_gap"] is True
    over = mon.observe(
        age_seconds=300.1,
        signal="present",
        previous_band="yellow",
        source="soak_summary_path",
        timestamp="2026-02-01T00:05:01Z",
        mono_seconds=300.1,
        log_path=path,
    )
    assert over["band"] == "red"
    assert over["red_exit"] is True
    missing = mon.observe(
        age_seconds=None,
        signal="missing",
        previous_band=None,
        source="runner_glob_unconfirmed",
        timestamp="2026-02-01T00:10:00Z",
        mono_seconds=0,
        log_path=path,
    )
    assert missing["record"]["gap_seconds"] is None
    assert missing["record"]["band"] == "red"
    assert missing["record"]["implies_soak_complete"] is False


def test_default_watch_source_is_not_a_live_soak_claim():
    assert gaps.watch_source(runner_glob=False, live_dut=False) == "soak_summary_path"
    assert gaps.watch_source(runner_glob=True, live_dut=False) == "runner_glob_unconfirmed"
    assert gaps.watch_source(runner_glob=False, live_dut=True) == "soak_summary_live"
    assert gaps.watch_source(runner_glob=True, live_dut=True) == "runner_glob_live"
    with pytest.raises(gaps.GapLogError):
        gaps.build_record(
            gap_seconds=1,
            source="soak_complete",
            timestamp="2026-02-01T00:00:00Z",
        )


def test_cli_appends_only_to_the_given_file(tmp_path: Path):
    out = tmp_path / "sample.jsonl"
    repo_log = ROOT / "docs" / "progress" / "coverage_gaps.jsonl"
    assert not repo_log.exists()
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "coverage_gap_log.py"),
            "--gap-seconds",
            "30",
            "--source",
            "operator_sample",
            "--timestamp",
            "2026-02-01T00:00:30Z",
            "--mono-seconds",
            "30",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["band"] == "yellow"
    assert row["implies_soak_complete"] is False
    assert not repo_log.exists()
    bad = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "coverage_gap_log.py"),
            "--gap-seconds",
            "-5",
            "--source",
            "operator_sample",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 2


def test_logger_record_scores_as_a_gap_and_still_cannot_accept():
    doc = json.loads(
        (ROOT / "tests" / "fixtures" / "l2_2" / "scaffold_full_wall_cannot_accept.json").read_text(
            encoding="utf-8"
        )
    )
    record = gaps.build_record(
        gap_seconds=30,
        source="soak_summary_live",
        timestamp="2026-02-01T01:00:00Z",
        mono_seconds=3600,
    )
    doc["supervision"]["coverage_gaps"] = [record]
    report = l2.score(doc)
    assert report["coverage_gaps"]["yellow"] == 1
    assert report["coverage_gaps"]["red"] == 0
    assert report["triage"]["business"] is False
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["gates"]["can_close_l2_2"] is False
    doc["supervision"]["coverage_gaps"] = [
        {"timestamp": "2026-02-01T01:00:00Z", "gap_seconds": 30, "band": "ok"}
    ]
    with pytest.raises(l2.CaptureError, match="does not match"):
        l2.score(doc)


def test_modules_do_not_register_tasks_or_start_the_soak():
    for name in ("coverage_gap_log.py", "supervision_monitor.py"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        for token in (
            "subprocess",
            "os.system",
            "Popen",
            "Register-ScheduledTask",
            "Enable-ScheduledTask",
            "schtasks ",
            "schtasks.exe",
        ):
            assert token not in text, name
    checklist = (ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md").read_text(encoding="utf-8")
    assert "NOT STARTED" in checklist
    assert "scripts/coverage_gap_log.py" in checklist
    assert "can_start_clock" in checklist
    assert "259200" in checklist
    lowered = checklist.lower()
    assert "register-scheduledtask" not in lowered
    assert "schtasks " not in lowered
