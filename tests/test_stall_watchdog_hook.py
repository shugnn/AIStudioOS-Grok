"""Offline stall-watchdog hook. Synthetic files only. Not a 72h start."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_gap_log as gaplog  # noqa: E402
import stall_watchdog as watchdog  # noqa: E402

SUMMARY = ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl"
METRICS = ROOT / "docs" / "progress" / "soak_2h" / "metrics.json"
ALERT = ROOT / "docs" / "progress" / "STALL_ALERT.json"
GAPS = ROOT / "docs" / "progress" / "coverage_gaps.jsonl"
STOP = ROOT / "docs" / "progress" / "EMERGENCY_STOP"


def time_now() -> float:
    return time.time()


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_state() -> dict[Path, str | None]:
    return {path: _digest(path) for path in (SUMMARY, METRICS, ALERT, GAPS, STOP)}


def test_offline_probe_classifies_synthetic_files_and_leaves_the_repo_alone():
    before = _tree_state()
    assert before[ALERT] is None
    assert before[STOP] is None
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    assert metrics["wall_elapsed_s"] == 86400.001
    assert metrics["wall_elapsed_s"] < 259200
    result = watchdog.offline_probe()
    assert result["ok"] is True
    assert result["detail"] == "synthetic_fresh_vs_stale"
    assert result["dut"] == "synthetic_temp_summary"
    assert result["ubuntu_24h_used_as_dut"] is False
    assert result["default_summary_used"] is False
    assert result["fresh_stalled"] is False
    assert result["stale_stalled"] is True
    assert result["fresh_exit"] == 0
    assert result["stale_exit"] == 1
    assert result["fresh_gap_band"] == "ok"
    assert result["stale_gap_band"] == "red"
    assert result["fresh_age_seconds"] < gaplog.YELLOW_MIN_SECONDS
    assert result["stale_age_seconds"] > gaplog.RED_MIN_SECONDS
    assert result["stale_age_seconds"] > result["stall_idle_seconds"]
    assert result["gap_source"] == "operator_sample"
    assert result["gap_appended"] is False
    assert result["gap_implies_soak_complete"] is False
    assert result["composed_with"] == "scripts/coverage_gap_log.py"
    assert result["clock_effect"] == "none"
    assert result["soak_launched"] is False
    assert result["binds_clock_start"] is False
    assert result["implies_l2_2_acceptance"] is False
    assert result["implies_72h_pass"] is False
    assert result["production_7x24"] == "NOT_ACCEPTED"
    assert result["can_start_clock"] is False
    assert result["can_accept_l2_2"] is False
    assert result["can_close_l2_2"] is False
    assert result["repo_alert_written"] is False
    assert result["alert_left_in_repo"] is False
    assert "l2_2_status" not in result
    assert _tree_state() == before
    assert not ALERT.exists()
    assert not STOP.exists()


def test_hook_refuses_ubuntu_24h_summary_without_reading_or_alerting(monkeypatch: pytest.MonkeyPatch):
    before = _tree_state()
    assert watchdog.ended_soak_tree(SUMMARY) is True
    assert watchdog.ended_soak_tree(METRICS) is True
    real_read = Path.read_text

    def _guard_read(self: Path, *args, **kwargs):
        if "soak_2h" in self.as_posix():
            raise AssertionError("hook read the ended soak tree")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _guard_read)
    code, payload = watchdog.hook_classify(
        SUMMARY,
        max_idle_minutes=watchdog.PROBE_MAX_IDLE_MINUTES,
        alert_path=ALERT,
    )
    assert code == 2
    assert payload["error"] == "ended_experiment_refused"
    assert payload["ubuntu_24h_used_as_dut"] is True
    assert payload.get("stalled") is not True
    assert payload["soak_launched"] is False
    assert payload["clock_effect"] == "none"
    assert payload.get("can_start_clock") is not True
    assert _tree_state() == before
    assert not ALERT.exists()


def test_hook_refuses_to_write_the_repo_alert(tmp_path: Path):
    summary = tmp_path / "fresh_summary.jsonl"
    summary.write_text(json.dumps({"utc": "2026-02-01T00:00:00Z", "synthetic": True}) + "\n", encoding="utf-8")
    now = os.path.getmtime(summary)
    before = _digest(ALERT)
    code, payload = watchdog.hook_classify(
        summary,
        max_idle_minutes=15,
        alert_path=ALERT,
        now=now,
    )
    assert code == 2
    assert payload["error"] == "repo_alert_refused"
    assert payload["ubuntu_24h_used_as_dut"] is False
    assert payload["soak_launched"] is False
    assert _digest(ALERT) == before
    assert not ALERT.exists()


def test_cli_fresh_and_stale_use_a_temp_alert(tmp_path: Path):
    before = _tree_state()
    fresh = tmp_path / "fresh_summary.jsonl"
    stale = tmp_path / "stale_summary.jsonl"
    alert = tmp_path / "STALL_ALERT.json"
    line = json.dumps({"utc": "2026-02-01T00:00:00Z", "synthetic": True, "label": "scaffold"}) + "\n"
    fresh.write_text(line, encoding="utf-8")
    stale.write_text(line, encoding="utf-8")
    now = time_now()
    os.utime(fresh, (now, now))
    os.utime(stale, (now - 960, now - 960))
    script = ROOT / "scripts" / "stall_watchdog.py"
    fresh_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--summary",
            str(fresh),
            "--alert",
            str(alert),
            "--max-idle-minutes",
            "15",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert fresh_run.returncode == 0, fresh_run.stderr
    fresh_doc = json.loads(fresh_run.stdout)
    assert fresh_doc["stalled"] is False
    assert fresh_doc["ok"] is True
    assert not alert.exists()
    stale_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--summary",
            str(stale),
            "--alert",
            str(alert),
            "--max-idle-minutes",
            "15",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert stale_run.returncode == 1, stale_run.stdout
    stale_doc = json.loads(stale_run.stdout)
    assert stale_doc["stalled"] is True
    assert stale_doc["ok"] is False
    assert alert.is_file()
    assert json.loads(alert.read_text(encoding="utf-8"))["stalled"] is True
    assert SUMMARY.as_posix() not in fresh_run.stdout
    assert SUMMARY.as_posix() not in stale_run.stdout
    assert "soak_2h" not in fresh_run.stdout
    assert "soak_2h" not in stale_run.stdout
    assert _tree_state() == before
    assert not (ROOT / "docs" / "progress" / "STALL_ALERT.json").exists()


def test_default_summary_is_the_ended_soak_and_the_hook_does_not_call_main(monkeypatch: pytest.MonkeyPatch):
    source = (ROOT / "scripts" / "stall_watchdog.py").read_text(encoding="utf-8")
    assert "import soak_2h" not in source
    assert "soak_2h.main" not in source
    assert "schtasks.exe" not in source
    assert "Register-ScheduledTask" not in source
    assert "Enable-ScheduledTask" not in source
    assert watchdog.DEFAULT_SUMMARY == SUMMARY
    assert watchdog.ended_soak_tree(watchdog.DEFAULT_SUMMARY) is True
    before = _tree_state()

    def boom(*_args, **_kwargs):
        raise AssertionError("offline hook called stall_watchdog.main")

    monkeypatch.setattr(watchdog, "main", boom)
    result = watchdog.offline_probe()
    assert result["ok"] is True
    assert result["default_summary_used"] is False
    assert result["ubuntu_24h_used_as_dut"] is False
    assert _tree_state() == before


def test_health_check_commands_do_not_point_the_watchdog_at_soak_2h():
    """The default CLI would watch Ubuntu-24H. These commands do not invoke it."""
    text = (ROOT / "scripts" / "l2_2_preflight.py").read_text(encoding="utf-8")
    assert "stall_watchdog.main" not in text
    assert "offline_probe" in text
    import health_check as hc

    commands = hc.l2_2_commands()
    blob = " ".join(" ".join(cmd) for cmd in commands)
    assert "stall_watchdog.py" not in blob
    assert "soak_2h" not in blob
    assert "schtasks" not in blob
