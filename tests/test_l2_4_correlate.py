"""L2-4 correlation helper. Fixtures are synthetic. They are not host reboot logs."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import l2_4_correlate as l2  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "l2_4"
SCHEMA_DOC = ROOT / "docs" / "progress" / "l2_4" / "SCHEMA.json"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _dt(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=timezone.utc)


def test_schema_ids_match_contract():
    doc = json.loads(SCHEMA_DOC.read_text(encoding="utf-8"))
    assert doc["capture_schema"] == l2.SCHEMA_CAPTURE
    assert doc["report_schema"] == l2.SCHEMA_REPORT
    assert doc["window_seconds_default"] == l2.DEFAULT_WINDOW_S
    assert doc["l2_4_status_emitted"] == "INCOMPLETE"
    assert doc["production_7x24"] == "NOT_ACCEPTED"
    assert doc["causation"] == "not_proven"


def test_strength_bands():
    window = 600.0
    moderate = l2.correlate_timestamps([_dt(0), _dt(0, 1)], [_dt(0), _dt(0, 1)], window)
    assert moderate["strength"] == "moderate"
    assert moderate["error_count"] == 2

    strong = l2.correlate_timestamps(
        [_dt(0, 0, 10), _dt(0, 10, 10), _dt(0, 20, 10)],
        [_dt(0), _dt(0, 10), _dt(0, 20)],
        window,
    )
    assert strong["strength"] == "strong"
    assert strong["match_ratio"] == 1.0

    two_of_three = l2.correlate_timestamps([_dt(0), _dt(0, 1), _dt(3)], [_dt(0)], window)
    assert two_of_three["matched_within_window"] == 2
    assert two_of_three["strength"] == "moderate"

    one_of_three = l2.correlate_timestamps([_dt(0), _dt(2), _dt(3)], [_dt(0)], window)
    assert one_of_three["strength"] == "weak"

    none = l2.correlate_timestamps([_dt(5)], [_dt(0)], window)
    assert none["strength"] == "none"

    no_anchor = l2.correlate_timestamps([_dt(0)], [], window)
    assert no_anchor["strength"] == "no_anchor"

    no_events = l2.correlate_timestamps([], [_dt(0)], window)
    assert no_events["strength"] == "no_events"


def test_strong_overlap_stays_incomplete():
    report = l2.correlate(_load("scaffold_strong_time_overlap.json"))
    assert report["label"] == "scaffold"
    assert report["verified"] is False
    assert report["l2_4_status"] == "INCOMPLETE"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["causation"] == "not_proven"
    assert report["business_fail"] is False
    assert report["gates"]["can_close_l2_4"] is False
    series = report["correlation"]["wt_vs_task_runs"]
    assert report["correlation"]["basis"] == "task_runs"
    assert report["correlation"]["strength"] == "strong"
    assert series["matched_within_window"] == 5
    assert series["median_abs_delta_seconds"] == 45.0
    assert report["reboot_residue"]["detected"] is True
    assert report["reboot_residue"]["aligned_with_reboot_event"] is True
    assert report["triage"] == {"business": False, "host": True, "supervision": True}
    assert "business" not in report["attribution"]
    assert report["wake_bar_20_met"] is False
    blockers = report["gates"]["blockers"]
    assert "scaffold_fixture_not_host_evidence" in blockers
    assert "strong_time_correlation_unexplained" in blockers
    assert "time_correlation_is_not_causation" in blockers
    assert "tasks_ready_with_empty_next_run_time" in blockers
    assert "process_tree_unavailable" in blockers
    assert l2.validate_report(report) == []
    assert "not the 2026-11-04 host log" in report["source"]["note"]


def test_twenty_scheduler_wakes_do_not_close_gate():
    doc = _load("scaffold_strong_time_overlap.json")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    runs = []
    errors = []
    for i in range(20):
        stamp = base + timedelta(minutes=10 * i)
        runs.append(
            {
                "utc": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "task_name": "AIStudioOS-Grok-L1",
                "event_id": 200,
            }
        )
        err = stamp + timedelta(seconds=45)
        errors.append(
            {
                "utc": err.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event_id": 1000,
                "faulting_application": "WindowsTerminal.exe",
            }
        )
    doc["task_runs"] = runs
    doc["wt_errors"] = errors
    report = l2.correlate(doc)
    assert report["wake_count"] == 20
    assert report["wake_bar_20_met"] is True
    assert report["correlation"]["strength"] == "strong"
    assert report["l2_4_status"] == "INCOMPLETE"
    assert report["gates"]["can_close_l2_4"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"


def test_no_overlap_is_not_a_host_failure():
    report = l2.correlate(_load("scaffold_no_overlap.json"))
    assert report["correlation"]["strength"] == "none"
    assert report["correlation"]["wt_vs_task_runs"]["matched_within_window"] == 0
    assert report["reboot_residue"]["detected"] is False
    assert report["triage"]["host"] is False
    assert report["triage"]["supervision"] is False
    assert report["attribution"] == []
    assert report["console_policy"]["violations"] == []


def test_pythonw_is_a_policy_violation_and_not_a_pass():
    report = l2.correlate(_load("scaffold_pythonw_violation.json"))
    assert len(report["console_policy"]["violations"]) == 1
    assert "pythonw_forbidden" in report["gates"]["blockers"]
    assert report["correlation"]["strength"] == "no_events"
    assert report["l2_4_status"] == "INCOMPLETE"
    assert report["business_fail"] is False


def test_reboot_residue_blank_next_run_time():
    report = l2.correlate(_load("scaffold_reboot_residue.json"))
    residue = report["reboot_residue"]
    assert residue["detected"] is True
    assert residue["aligned_with_reboot_event"] is True
    names = {row["task_name"] for row in residue["tasks"]}
    assert names == {"AIStudioOS-Grok-L1", "AIStudioOS-Grok-Watchdog"}
    assert report["correlation"]["strength"] == "no_events"
    assert report["triage"]["host"] is True
    assert report["triage"]["business"] is False


def test_scheduler_history_beats_nearby_runner_file():
    report = l2.correlate(_load("scaffold_history_preferred.json"))
    assert report["correlation"]["basis"] == "task_runs"
    assert report["correlation"]["strength"] == "none"
    assert report["correlation"]["wt_vs_task_runs"]["strength"] == "none"
    runner = report["correlation"]["wt_vs_runner_artifacts"]
    assert runner["matched_within_window"] == 1
    assert runner["strength"] == "moderate"
    assert report["causation"] == "not_proven"


def test_unavailable_history_can_fall_back_to_snapshot_run_times():
    doc = _load("scaffold_no_overlap.json")
    doc["task_history"] = {"available": False, "error": "log disabled", "runs": []}
    doc["task_runs"] = []
    doc["tasks"][0]["run_times_utc"] = ["2026-01-01T06:00:10Z"]
    report = l2.correlate(doc)
    assert report["correlation"]["basis"] == "task_run_times_utc"
    assert "scheduler_history_not_in_capture" in report["gates"]["blockers"]
    assert report["correlation"]["wt_vs_task_runs"]["matched_within_window"] >= 1


def test_readable_empty_history_is_not_replaced_by_runner_files():
    doc = _load("scaffold_history_preferred.json")
    doc["task_history"] = {"available": True, "error": None, "runs": []}
    doc["task_runs"] = []
    report = l2.correlate(doc)
    assert report["correlation"]["basis"] == "task_runs"
    assert report["correlation"]["strength"] == "no_anchor"
    assert report["wake_count"] == 0
    assert "no_duty_anchors" in report["gates"]["blockers"]


def test_rejects_mislabeled_and_non_wt_events():
    labeled = _load("scaffold_strong_time_overlap.json")
    labeled["evidence_class"] = "host_capture"
    with pytest.raises(l2.CaptureError):
        l2.correlate(labeled)

    foreign = _load("scaffold_no_overlap.json")
    foreign["wt_errors"][0]["faulting_application"] = "explorer.exe"
    with pytest.raises(l2.CaptureError):
        l2.correlate(foreign)

    bad_id = _load("scaffold_no_overlap.json")
    bad_id["wt_errors"][0]["event_id"] = 1001
    with pytest.raises(l2.CaptureError):
        l2.correlate(bad_id)

    bad_reboot = _load("scaffold_reboot_residue.json")
    bad_reboot["reboots"][0]["event_id"] = 1
    with pytest.raises(l2.CaptureError):
        l2.correlate(bad_reboot)

    naive = _load("scaffold_naive_timestamp.json")
    with pytest.raises(l2.CaptureError):
        l2.correlate(naive)


def test_process_tree_and_truncation_still_do_not_prove_causation():
    doc = _load("scaffold_no_overlap.json")
    doc["process_tree"] = {
        "available": True,
        "links": [{"parent_image": "python.exe", "child_image": "WindowsTerminal.exe"}],
    }
    report = l2.correlate(doc)
    assert report["causation"] == "not_proven"
    assert report["process_tree"]["status"] == "present"
    assert "process_tree_present_but_causation_not_declared" in report["gates"]["blockers"]
    assert report["gates"]["can_close_l2_4"] is False

    truncated = _load("scaffold_strong_time_overlap.json")
    truncated["application_error_1000"] = {
        "total_in_window": 5000,
        "truncated": True,
        "query_available": False,
        "by_faulting_application": [],
    }
    report = l2.correlate(truncated)
    blockers = report["gates"]["blockers"]
    assert "wt_error_list_truncated" in blockers
    assert "application_error_query_failed" in blockers
    assert report["l2_4_status"] == "INCOMPLETE"


def test_forged_pass_report_is_rejected():
    forged = {
        "schema": l2.SCHEMA_REPORT,
        "evidence_class": "host_capture",
        "production_7x24": "ACCEPTED",
        "l2_4_status": "PASS",
        "causation": "proven",
        "verified": True,
        "business_fail": True,
        "gates": {"can_close_l2_4": True},
    }
    violations = set(l2.validate_report(forged))
    assert "forged_pass" in violations
    assert "production_claim" in violations
    assert "causation_proven_forbidden" in violations
    assert "forged_close" in violations
    assert "verified_claim" in violations
    assert "business_fail_not_supported" in violations


def test_cli_scaffold_exit_0_and_invalid_exit_2(tmp_path: Path):
    script = ROOT / "scripts" / "l2_4_correlate.py"
    out = tmp_path / "report.json"
    ok = subprocess.run(
        [
            sys.executable,
            str(script),
            "--capture",
            str(FIXTURES / "scaffold_strong_time_overlap.json"),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["l2_4_status"] == "INCOMPLETE"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert l2.validate_report(report) == []

    bad = subprocess.run(
        [sys.executable, str(script), "--capture", str(FIXTURES / "scaffold_naive_timestamp.json")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 2
    payload = json.loads(bad.stdout)
    assert payload["ok"] is False
    assert "naive" in payload["detail"]


def test_capture_script_is_read_only_and_names_the_schema():
    text = (ROOT / "scripts" / "l2_4_capture_host.ps1").read_text(encoding="utf-8")
    assert l2.SCHEMA_CAPTURE in text
    assert "host_capture" in text
    stripped = re.sub(r"<#.*?#>", "", text, flags=re.S)
    code_lines = [line.split("#", 1)[0] for line in stripped.splitlines()]
    code = "\n".join(code_lines).lower()
    for token in (
        "register-scheduledtask",
        "start-scheduledtask",
        "stop-scheduledtask",
        "enable-scheduledtask",
        "disable-scheduledtask",
        "unregister-scheduledtask",
        "set-scheduledtask",
        "schtasks",
    ):
        assert token not in code
    # PS 5.1 Set-StrictMode rejects @($genericList) inside an [ordered] literal.
    for line in (
        "task_runs       = $taskRuns.ToArray()",
        "runner_artifacts = $runnerArtifacts.ToArray()",
        "wt_errors       = $wtErrors.ToArray()",
        "reboots         = $reboots.ToArray()",
        "reboot_query_errors = $rebootErrors.ToArray()",
        "by_faulting_application  = $histogram.ToArray()",
    ):
        assert line in text
    for wrapped in (
        "@($taskRuns)",
        "@($runnerArtifacts)",
        "@($wtErrors)",
        "@($reboots)",
        "@($rebootErrors)",
        "@($histogram)",
    ):
        assert wrapped not in text
    assert "No events were found|找不到任何与指定的选择条件匹配的事件" in text


def test_committed_host_capture_stays_incomplete():
    """Second LAPTOP-Q14O4JJT export, after Operational history was enabled.

    The log does not backfill. task_runs stays an empty readable list.
    """
    host = ROOT / "docs" / "progress" / "l2_4" / "host"
    capture_bytes = (host / "capture.json").read_bytes()
    report_bytes = (host / "report.json").read_bytes()
    assert hashlib.sha256(capture_bytes).hexdigest() == (
        "e5754bc53b412dd87156943a6f2cb9b29d61d47c63586d11fc2cdfbc387996bc"
    )
    assert hashlib.sha256(report_bytes).hexdigest() == (
        "2cf000698f72af7b1135da6842f9474628f594dde47adb5141b86e3b9dc277a4"
    )
    capture = json.loads(capture_bytes)
    report = json.loads(report_bytes)
    assert capture["host"] == "LAPTOP-Q14O4JJT"
    assert capture["since_utc"] == "2026-11-03T00:00:00Z"
    assert capture["until_utc"] == "2026-11-06T00:00:00Z"
    assert capture["evidence_class"] == "host_capture"
    assert capture["synthetic"] is False
    assert capture["collector_mode"] == "read_only"
    assert capture["wt_errors"] == []
    assert capture["task_runs"] == []
    assert capture["task_history"]["available"] is True
    assert capture["task_history"]["error"] is None
    assert capture["task_history"]["runs"] == []
    assert len(capture["reboots"]) == 6
    assert len(capture["runner_artifacts"]) == 133
    assert capture["application_error_1000"]["total_in_window"] == 1
    assert capture["application_error_1000"]["by_faulting_application"] == [
        {"name": "Explorer.EXE", "count": 1}
    ]
    assert report["l2_4_status"] == "INCOMPLETE"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["causation"] == "not_proven"
    assert report["verified"] is False
    assert report["label"] == "host_capture_unverified"
    assert report["correlation"]["basis"] == "task_runs"
    assert report["correlation"]["strength"] == "no_events"
    assert report["reboot_residue"]["detected"] is False
    assert report["wake_count"] == 0
    assert report["wake_bar_20_met"] is False
    assert report["gates"]["can_close_l2_4"] is False
    assert "scheduler_history_not_in_capture" not in report["gates"]["blockers"]
    assert report["gates"]["blockers"] == [
        "tool_does_not_close_gate",
        "time_correlation_is_not_causation",
        "founder_reapproval_required_before_new_interactive_duty",
        "process_tree_unavailable",
        "no_duty_anchors",
        "fewer_than_20_duty_wakes",
    ]
    assert l2.validate_report(report) == []
