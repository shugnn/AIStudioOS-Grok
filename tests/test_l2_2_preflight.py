"""Offline L2-2 preflight. It reports NOT_STARTED and does not launch soak."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_gap_log as gaplog  # noqa: E402
import evidence_sha256sums as sums_tool  # noqa: E402
import l2_2_preflight as pre  # noqa: E402
import l2_2_score as l2  # noqa: E402
import soak_2h  # noqa: E402
import stall_watchdog  # noqa: E402
import supervision_monitor  # noqa: E402

COMMITTED = ROOT / "docs" / "progress" / "l2_2" / "scaffold" / "preflight.json"
RUNTIME_PATHS = (
    ROOT / "docs" / "progress" / "EMERGENCY_STOP",
    ROOT / "docs" / "progress" / "coverage_gaps.jsonl",
    ROOT / "docs" / "progress" / "soak_2h" / "metrics.json",
    ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl",
    ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md",
    ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md",
    ROOT / "docs" / "progress" / "STALL_ALERT.json",
)


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_not_a_start(report: dict) -> None:
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["clock_effect"] == "none"
    assert report["soak_launched"] is False
    assert report["documented_soak_argv_executed"] is False
    assert report["interactive_tasks_registered"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["product_l2_task_split"] == "NOT_STARTED"
    assert report["gate_result"] == "NOT_A_GATE"
    assert report["exit_0_is_gate_pass"] is False
    assert report["verified"] is False
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_close_l2_2"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["l2_4"]["status"] == "INCOMPLETE"
    assert report["l2_4"]["relitigated"] is False
    assert "not a start decision" in report["operator_note"]
    text = json.dumps(report)
    assert '"can_start_clock": true' not in text
    assert '"can_accept_l2_2": true' not in text
    assert '"can_close_l2_2": true' not in text
    assert pre.validate_report(report) == []


def test_real_repo_preflight_is_not_started_and_intact():
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is True
    assert report["failures"] == []
    assert report["checks"]["scaffold_files"]["missing"] == []
    sums_check = report["checks"]["evidence_sums"]
    assert sums_check["ok"] is True
    assert sums_check["detail"] == "bound_not_a_start"
    assert sums_check["binds_clock_start"] is False
    assert sums_check["self_report_listed"] is True
    assert sums_check["mismatched"] == []
    assert sums_check["missing_from_sums"] == []
    assert report["checks"]["soak_flags"]["action"] == "argparse_only"
    assert report["checks"]["soak_flags"]["executed"] is False
    assert report["checks"]["soak_flags"]["via_l1"] is True
    assert report["checks"]["soak_flags"]["idle_policy"] == "reseed"
    assert report["checks"]["soak_flags"]["max_wall_seconds"] == 259200
    assert report["checks"]["r2_checklist"]["unfilled"] is True
    assert report["checks"]["r2_checklist"]["start_decision"] == "not_given"
    decision = report["checks"]["start_decision"]
    assert decision["ok"] is True
    assert decision["unfilled"] is True
    assert decision["start_decision"] == "not_given"
    assert decision["detail"] == "blank_template"
    assert decision["binds_clock_start"] is False
    assert report["checks"]["emergency_stop"]["flag_present"] is False
    assert report["checks"]["emergency_stop"]["path"] == "docs/progress/EMERGENCY_STOP"
    assert report["checks"]["gap_logger"]["sample_band"] == "yellow"
    assert report["checks"]["gap_logger"]["sample_timestamp"] == "2026-02-01T00:00:30Z"
    assert report["checks"]["gap_logger"]["implies_soak_complete"] is False
    assert report["checks"]["gap_logger"]["clock_effect"] == "none"
    assert report["checks"]["gap_logger"]["appended"] is False
    assert report["checks"]["supervision_monitor"]["action"] == "argparse_only"
    assert report["checks"]["supervision_monitor"]["wired_to_gap_logger"] is True
    assert report["checks"]["supervision_monitor"]["live_dut_switch_parses"] is True
    assert report["checks"]["supervision_monitor"]["executed"] is False
    stall = report["checks"]["stall_watchdog"]
    assert stall["ok"] is True
    assert stall["detail"] == "synthetic_fresh_vs_stale"
    assert stall["action"] == "synthetic_mtime"
    assert stall["dut"] == "synthetic_temp_summary"
    assert stall["ubuntu_24h_used_as_dut"] is False
    assert stall["default_summary_used"] is False
    assert stall["fresh_stalled"] is False
    assert stall["stale_stalled"] is True
    assert stall["fresh_exit"] == 0
    assert stall["stale_exit"] == 1
    assert stall["fresh_gap_band"] == "ok"
    assert stall["stale_gap_band"] == "red"
    assert stall["gap_source"] == "operator_sample"
    assert stall["gap_appended"] is False
    assert stall["gap_implies_soak_complete"] is False
    assert stall["composed_with"] == "scripts/coverage_gap_log.py"
    assert stall["clock_effect"] == "none"
    assert stall["soak_launched"] is False
    assert stall["binds_clock_start"] is False
    assert stall["implies_l2_2_acceptance"] is False
    assert stall["implies_72h_pass"] is False
    assert stall["l2_2_status"] == "NOT_STARTED"
    assert stall["clock_state"] == "NOT_STARTED"
    assert stall["production_7x24"] == "NOT_ACCEPTED"
    assert stall["can_start_clock"] is False
    assert stall["repo_alert_written"] is False
    assert stall["alert_left_in_repo"] is False
    assert "soak_2h" not in json.dumps(stall)
    assert report["checks"]["scorer_refuses"]["status"] == "NOT_STARTED"
    assert report["checks"]["scorer_refuses"]["gates_false"] is True
    assert report["checks"]["scorer_refuses"]["forged_pass_rejected"] is True
    assert report["checks"]["scorer_refuses"]["forged_clock_rejected"] is True
    assert report["checks"]["scorer_refuses"]["forged_accept_rejected"] is True
    assert report["checks"]["scorer_refuses"]["forged_close_rejected"] is True
    assert report["schema"] == pre.SCHEMA
    assert "259200" in report["documented_soak_argv"]
    assert "--via-l1" in report["documented_soak_argv"]
    assert "reseed" in report["documented_soak_argv"]


def test_committed_preflight_matches_the_tool():
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    fresh = pre.preflight()
    assert committed == fresh
    assert committed["l2_2_status"] == "NOT_STARTED"
    assert committed["not_started_scaffold_intact"] is True


def test_validate_rejects_clock_start_accept_close_and_pass():
    report = pre.preflight()
    for key in ("can_start_clock", "can_accept_l2_2", "can_close_l2_2"):
        forged = json.loads(json.dumps(report))
        forged["gates"][key] = True
        assert "forged_" + key in pre.validate_report(forged)
    forged = json.loads(json.dumps(report))
    forged["l2_2_status"] = "PASS"
    assert "status" in pre.validate_report(forged)
    forged = json.loads(json.dumps(report))
    forged["soak_launched"] = True
    assert "soak_launched" in pre.validate_report(forged)
    forged = json.loads(json.dumps(report))
    forged["exit_0_is_gate_pass"] = True
    assert "exit_0_claim" in pre.validate_report(forged)


def test_cli_exit_0_does_not_touch_runtime_files(tmp_path: Path):
    before = {path: _digest(path) for path in RUNTIME_PATHS}
    assert before[ROOT / "docs" / "progress" / "EMERGENCY_STOP"] is None
    out = tmp_path / "preflight.json"
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l2_2_preflight.py"), "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is True
    assert json.loads(out.read_text(encoding="utf-8")) == report
    after = {path: _digest(path) for path in RUNTIME_PATHS}
    assert after == before


def test_cli_exit_2_on_empty_root_still_refuses_start(tmp_path: Path):
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l2_2_preflight.py"), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 2, done.stdout
    report = json.loads(done.stdout)
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is False
    assert report["checks"]["scaffold_files"]["ok"] is False
    assert report["soak_launched"] is False
    assert not (tmp_path / "docs" / "progress" / "EMERGENCY_STOP").exists()


def test_filled_checklist_is_not_a_start(tmp_path: Path):
    text = (ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md").read_text(encoding="utf-8")
    filled = text.replace("**Not given**", "**Ada 2026-02-01T00:00:00Z**", 1)
    path = tmp_path / "R2_CHECKLIST.md"
    path.write_text(filled, encoding="utf-8")
    report = pre.preflight(checklist_path=path)
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is False
    assert report["checks"]["r2_checklist"]["ok"] is False
    assert report["checks"]["r2_checklist"]["start_decision"] == "blank_template_changed"
    assert report["checks"]["r2_checklist"]["start_decision"] != "given"
    assert "r2_checklist:checklist_not_blank" in report["failures"]
    original = (ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md").read_text(encoding="utf-8")
    assert "**Not given**" in original


def test_emergency_stop_present_is_left_untouched(tmp_path: Path):
    stop = tmp_path / "EMERGENCY_STOP"
    stop.write_text("founder halt\n", encoding="utf-8")
    before = stop.read_bytes()
    report = pre.preflight(stop_path=stop)
    _assert_not_a_start(report)
    assert stop.read_bytes() == before
    assert report["checks"]["emergency_stop"]["flag_present"] is True
    assert report["checks"]["emergency_stop"]["ok"] is False
    assert report["not_started_scaffold_intact"] is False
    assert "emergency_stop:present_left_untouched" in report["failures"]
    assert not (ROOT / "docs" / "progress" / "EMERGENCY_STOP").exists()


def test_stop_path_matches_the_control_plane_flag():
    import control_plane.emergency_stop as es

    assert pre.default_stop_path() == es.STOP_PATH
    assert pre.default_stop_path().name == "EMERGENCY_STOP"
    assert pre.default_stop_path().name != "EMERGENCY_STOP.md"


def test_soak_flags_are_parsed_not_executed(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    def boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("soak or monitor main was called")

    monkeypatch.setattr(soak_2h, "main", boom)
    monkeypatch.setattr(supervision_monitor, "main", boom)
    monkeypatch.setattr(stall_watchdog, "main", boom)
    monkeypatch.setattr(gaplog, "append_record", boom)
    bare = soak_2h.build_parser().parse_args([])
    assert bare.via_l1 is False
    assert bare.idle_policy == "stop"
    assert bare.max_wall_seconds == 0
    report = pre.preflight()
    assert calls["n"] == 0
    _assert_not_a_start(report)
    assert report["checks"]["soak_flags"]["detail"] == "parsed_not_executed"
    assert report["checks"]["supervision_monitor"]["detail"] == "parsed_not_executed"
    assert report["checks"]["stall_watchdog"]["detail"] == "synthetic_fresh_vs_stale"
    assert report["checks"]["stall_watchdog"]["soak_launched"] is False


def test_missing_soak_flag_fails_closed(monkeypatch: pytest.MonkeyPatch):
    def bad_parser():
        import argparse

        ap = argparse.ArgumentParser()
        ap.add_argument("--cycles", type=int, default=1)
        return ap

    monkeypatch.setattr(soak_2h, "build_parser", bad_parser)
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["checks"]["soak_flags"]["ok"] is False
    assert report["checks"]["soak_flags"]["executed"] is False
    assert report["not_started_scaffold_intact"] is False
    assert report["gates"]["can_start_clock"] is False


def test_scorer_false_pass_cannot_flip_preflight_gates(monkeypatch: pytest.MonkeyPatch):
    real_score = l2.score

    def evil(doc):
        scored = real_score(doc)
        scored["l2_2_status"] = "PASS"
        scored["gates"]["can_start_clock"] = True
        scored["gates"]["can_accept_l2_2"] = True
        scored["gates"]["can_close_l2_2"] = True
        scored["production_7x24"] = "ACCEPTED"
        return scored

    monkeypatch.setattr(l2, "score", evil)
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["checks"]["scorer_refuses"]["ok"] is False
    assert report["checks"]["scorer_refuses"]["status"] == "withheld"
    assert report["checks"]["scorer_refuses"]["detail"] == "scorer_would_overclaim"
    assert report["not_started_scaffold_intact"] is False
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["production_7x24"] == "NOT_ACCEPTED"


def test_main_refuses_to_print_a_start_gate(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    good = pre.preflight()

    def bad(*_args, **_kwargs):
        forged = json.loads(json.dumps(good))
        forged["gates"]["can_start_clock"] = True
        return forged

    monkeypatch.setattr(pre, "preflight", bad)
    assert pre.main([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == "refusing_overclaim"
    assert payload["l2_2_status"] == "NOT_STARTED"
    assert payload["soak_launched"] is False
    assert payload["gates"]["can_start_clock"] is False
    assert payload["exit_0_is_gate_pass"] is False
    assert '"can_start_clock": true' not in json.dumps(payload)


def test_preflight_source_does_not_launch_soak_or_register_tasks():
    text = (ROOT / "scripts" / "l2_2_preflight.py").read_text(encoding="utf-8")
    for token in (
        "subprocess",
        "os.system",
        "Popen",
        "soak_2h.main",
        "supervision_monitor.main",
        "Register-ScheduledTask",
        "Enable-ScheduledTask",
        "Start-ScheduledTask",
        "schtasks ",
        "schtasks.exe",
    ):
        assert token not in text
    assert "build_parser" in text
    assert "can_start_clock" in text
    assert "offline_probe" in text
    assert "stall_watchdog.main" not in text


def test_operator_notes_say_running_is_not_a_start():
    readme = (ROOT / "docs" / "progress" / "l2_2" / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md").read_text(encoding="utf-8")
    decision = (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "docs" / "progress" / "l2_2" / "SCHEMA.json").read_text(encoding="utf-8"))
    assert "scripts/l2_2_preflight.py" in readme
    assert "scripts/stall_watchdog.py" in readme
    assert "synthetic fresh summary" in readme
    assert "STALL_ALERT.json" in readme
    assert "86400.001" in readme
    assert "not a start decision" in readme
    assert "START_DECISION.md" in readme
    assert "--idle-policy reseed --max-wall-seconds 259200" in readme
    assert "not a start decision" in checklist
    assert "The copy in git is unfilled." in checklist
    assert pre.classify_r2(checklist)["start_decision"] == "not_given"
    assert "The copy in git is unfilled." in decision
    assert "Filling this file alone does not start the soak" in decision
    assert pre.INTENDED_COMMAND in decision
    assert pre.classify_start_decision(decision)["start_decision"] == "not_given"
    assert pre.classify_start_decision(decision)["ok"] is True
    assert schema["preflight_schema"] == pre.SCHEMA
    assert schema["can_start_clock"] is False
    assert "PASS" not in schema["l2_2_status_emitted"]
    assert any("SHA256SUMS.json" in note and "do not start" in note for note in schema["notes"])


def test_evidence_package_indexes_preflight_and_sums_as_not_started():
    text = (ROOT / "docs" / "progress" / "EVIDENCE_PACKAGE.md").read_text(encoding="utf-8")
    section = text.split("## L2-2", 1)[1].split("\n## ", 1)[0]
    assert "scripts/l2_2_preflight.py" in section
    assert "scripts/stall_watchdog.py" in section
    assert "synthetic fresh" in section
    assert "START_DECISION.md" in section
    assert "Filling this file alone does not start the soak" in section or "not a start" in section
    assert "scaffold/preflight.json" in section
    assert "SHA256SUMS.json" in section
    assert "scripts/evidence_sha256sums.py" in section
    assert "NOT STARTED" in section
    assert "NOT ACCEPTED" in section
    assert "pull/11" in section
    assert "931758cb7487d8c8ac1697f1b3ad1e2fa7610ef6" in section
    assert "does not recapture" in section


def test_sha256sums_bind_the_l2_2_tree_and_do_not_start():
    sums_path = ROOT / "docs" / "progress" / "l2_2" / "SHA256SUMS.json"
    doc = json.loads(sums_path.read_text(encoding="utf-8"))
    assert isinstance(doc.get("git_head"), str) and len(doc["git_head"]) == 40
    assert doc["count"] == len(doc["files"])
    listed = []
    for entry in doc["files"]:
        path = ROOT / entry["path"]
        assert path.is_file()
        assert path.stat().st_size == entry["bytes"]
        assert sums_tool.sha256_file(path) == entry["sha256"]
        listed.append(entry["path"])
    expected = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "docs" / "progress" / "l2_2").rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.json"
    )
    assert sorted(listed) == expected
    assert "docs/progress/l2_2/scaffold/preflight.json" in listed
    assert "docs/progress/l2_2/SHA256SUMS.json" not in listed
    assert "can_start_clock" not in doc
    assert doc.get("l2_2_status", "NOT_STARTED") != "PASS"
    assert doc.get("production_7x24", "NOT_ACCEPTED") != "ACCEPTED"


def test_tampered_sums_do_not_start_the_clock(tmp_path: Path):
    original = json.loads((ROOT / "docs" / "progress" / "l2_2" / "SHA256SUMS.json").read_text(encoding="utf-8"))
    flipped = json.loads(json.dumps(original))
    for entry in flipped["files"]:
        if entry["path"] != pre.SELF_REPORT:
            entry["sha256"] = "0" * 64
            break
    path = tmp_path / "SHA256SUMS.json"
    path.write_text(json.dumps(flipped), encoding="utf-8")
    report = pre.preflight(sums_path=path)
    _assert_not_a_start(report)
    assert report["checks"]["evidence_sums"]["ok"] is False
    assert report["checks"]["evidence_sums"]["detail"] == "mismatch"
    assert report["checks"]["evidence_sums"]["binds_clock_start"] is False
    assert report["not_started_scaffold_intact"] is False
    assert report["gates"]["can_start_clock"] is False


def test_sums_overclaim_cannot_flip_gates(tmp_path: Path):
    original = json.loads((ROOT / "docs" / "progress" / "l2_2" / "SHA256SUMS.json").read_text(encoding="utf-8"))
    poisoned = json.loads(json.dumps(original))
    poisoned["l2_2_status"] = "PASS"
    poisoned["production_7x24"] = "ACCEPTED"
    poisoned["can_start_clock"] = True
    poisoned["can_accept_l2_2"] = True
    poisoned["can_close_l2_2"] = True
    path = tmp_path / "SHA256SUMS.json"
    path.write_text(json.dumps(poisoned), encoding="utf-8")
    report = pre.preflight(sums_path=path)
    _assert_not_a_start(report)
    assert report["checks"]["evidence_sums"]["detail"] == "overclaim"
    assert report["checks"]["evidence_sums"]["binds_clock_start"] is False
    assert report["not_started_scaffold_intact"] is False
    assert '"production_7x24": "ACCEPTED"' not in json.dumps(report)
    assert '"l2_2_status": "PASS"' not in json.dumps(report)
    forged = json.loads(json.dumps(pre.preflight()))
    forged["checks"]["evidence_sums"]["binds_clock_start"] = True
    assert "sums_imply_start" in pre.validate_report(forged)


def test_blank_start_decision_is_accepted_and_is_not_a_start():
    path = ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md"
    text = path.read_text(encoding="utf-8")
    classified = pre.classify_start_decision(text)
    assert classified["ok"] is True
    assert classified["unfilled"] is True
    assert classified["start_decision"] == "not_given"
    assert classified["detail"] == "blank_template"
    assert classified["binds_clock_start"] is False
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is True
    assert report["checks"]["start_decision"] == classified
    assert "Filling START_DECISION.md is not a start decision." in report["operator_note"]
    assert any("START_DECISION.md" in step and "does not start" in step for step in report["next_steps"])


@pytest.mark.parametrize(
    "snippet",
    [
        "clock_state: STARTED",
        "l2_2_status: PASS",
        "production_7x24: ACCEPTED",
        "can_start_clock: true",
        "can_start_clock true",
        "can_accept_l2_2: true",
        "can_close_l2_2: true",
    ],
)
def test_forged_start_decision_language_fails_closed(tmp_path: Path, snippet: str):
    original = (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")
    path = tmp_path / "START_DECISION.md"
    path.write_text(original + "\n" + snippet + "\n", encoding="utf-8")
    report = pre.preflight(start_decision_path=path)
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is False
    check = report["checks"]["start_decision"]
    assert check["ok"] is False
    assert check["detail"] == "forged_claim"
    assert check["start_decision"] == "forge_refused"
    assert check["binds_clock_start"] is False
    assert check["start_decision"] not in {"given", "started", "approved"}
    assert "start_decision:forged_claim" in report["failures"]
    dumped = json.dumps(report)
    assert '"can_start_clock": true' not in dumped
    assert '"l2_2_status": "PASS"' not in dumped
    assert '"production_7x24": "ACCEPTED"' not in dumped
    assert '"clock_state": "STARTED"' not in dumped
    assert original == (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")


def test_removing_not_given_honesty_is_not_a_start(tmp_path: Path):
    original = (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")
    path = tmp_path / "START_DECISION.md"
    path.write_text(original.replace("**Not given**", "**Ada**", 1), encoding="utf-8")
    report = pre.preflight(start_decision_path=path)
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is False
    check = report["checks"]["start_decision"]
    assert check["ok"] is False
    assert check["detail"] == "not_blank"
    assert check["start_decision"] == "blank_template_changed"
    assert check["start_decision"] != "given"
    assert report["gates"]["can_start_clock"] is False
    assert "**Not given**" in original


def test_start_decision_field_cannot_imply_a_start():
    forged = json.loads(json.dumps(pre.preflight()))
    forged["checks"]["start_decision"]["start_decision"] = "started"
    assert "start_decision_implies_start" in pre.validate_report(forged)
    forged = json.loads(json.dumps(pre.preflight()))
    forged["checks"]["start_decision"]["binds_clock_start"] = True
    assert "start_decision_implies_start" in pre.validate_report(forged)
    forged = json.loads(json.dumps(pre.preflight()))
    forged["checks"]["start_decision"]["ok"] = True
    forged["checks"]["start_decision"]["detail"] = "forged_claim"
    assert "start_decision_implies_start" in pre.validate_report(forged)
    refused = pre.validate_report(pre.preflight())
    assert refused == []


def test_stall_hook_overclaim_cannot_start_the_clock(monkeypatch: pytest.MonkeyPatch):
    real = stall_watchdog.offline_probe()

    def evil():
        forged = json.loads(json.dumps(real))
        forged["l2_2_status"] = "PASS"
        forged["clock_state"] = "STARTED"
        forged["production_7x24"] = "ACCEPTED"
        forged["can_start_clock"] = True
        forged["implies_l2_2_acceptance"] = True
        forged["implies_72h_pass"] = True
        forged["binds_clock_start"] = True
        forged["ubuntu_24h_used_as_dut"] = True
        forged["soak_launched"] = True
        return forged

    monkeypatch.setattr(stall_watchdog, "offline_probe", evil)
    report = pre.preflight()
    _assert_not_a_start(report)
    stall = report["checks"]["stall_watchdog"]
    assert stall["ok"] is False
    assert stall["detail"] == "probe_overclaim"
    assert stall["l2_2_status"] == "NOT_STARTED"
    assert stall["clock_state"] == "NOT_STARTED"
    assert stall["production_7x24"] == "NOT_ACCEPTED"
    assert stall["can_start_clock"] is False
    assert stall["implies_l2_2_acceptance"] is False
    assert stall["ubuntu_24h_used_as_dut"] is False
    assert stall["soak_launched"] is False
    assert report["not_started_scaffold_intact"] is False
    assert report["gates"]["can_start_clock"] is False
    dumped = json.dumps(report)
    assert '"l2_2_status": "PASS"' not in dumped
    assert '"production_7x24": "ACCEPTED"' not in dumped
    assert '"clock_state": "STARTED"' not in dumped
    assert '"can_start_clock": true' not in dumped


def test_forged_stall_hook_report_is_not_a_start_or_acceptance():
    report = pre.preflight()
    forged = json.loads(json.dumps(report))
    forged["checks"]["stall_watchdog"]["implies_l2_2_acceptance"] = True
    forged["checks"]["stall_watchdog"]["binds_clock_start"] = True
    forged["checks"]["stall_watchdog"]["implies_72h_pass"] = True
    assert "stall_implies_start" in pre.validate_report(forged)
    forged = json.loads(json.dumps(report))
    forged["checks"]["stall_watchdog"]["l2_2_status"] = "PASS"
    forged["checks"]["stall_watchdog"]["can_start_clock"] = True
    forged["checks"]["stall_watchdog"]["production_7x24"] = "ACCEPTED"
    forged["checks"]["stall_watchdog"]["clock_state"] = "STARTED"
    names = pre.validate_report(forged)
    assert "status" in names
    assert "forged_can_start_clock" in names
    assert "production_claim" in names
    assert "clock_state" in names
    forged = json.loads(json.dumps(report))
    forged["checks"]["stall_watchdog"]["ubuntu_24h_used_as_dut"] = True
    forged["checks"]["stall_watchdog"]["default_summary_used"] = True
    assert "stall_ubuntu_dut" in pre.validate_report(forged)
    forged = json.loads(json.dumps(report))
    forged["checks"]["stall_watchdog"]["ok"] = True
    forged["checks"]["stall_watchdog"]["fresh_stalled"] = True
    forged["checks"]["stall_watchdog"]["stale_stalled"] = False
    assert "stall_classification" in pre.validate_report(forged)
    assert report["gates"]["can_start_clock"] is False


def test_committed_ubuntu_24h_is_a_short_specimen_not_the_72h_gate(monkeypatch: pytest.MonkeyPatch):
    metrics_path = ROOT / "docs" / "progress" / "soak_2h" / "metrics.json"
    summary_path = ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl"
    before = metrics_path.read_bytes()
    summary_before = summary_path.read_bytes()
    metrics = json.loads(before)
    assert metrics["experiment"] == "UBUNTU-24H"
    assert metrics["wall_elapsed_s"] == 86400.001
    assert metrics["wall_elapsed_s"] < 259200
    assert metrics["max_wall_seconds"] == 86400
    seen: list[str] = []
    real_score = l2.score

    def wrapped(doc):
        clock = doc.get("clock") if isinstance(doc, dict) else None
        assert not (isinstance(clock, dict) and clock.get("started") is True)
        assert doc.get("host") != metrics["host"]
        seen.append(doc.get("evidence_class"))
        return real_score(doc)

    monkeypatch.setattr(l2, "score", wrapped)
    report = pre.preflight()
    _assert_not_a_start(report)
    assert seen == ["scaffold", "scaffold", "scaffold", "scaffold", "scaffold"]
    specimen = report["ubuntu_24h_specimen"]
    assert specimen == report["checks"]["ubuntu_24h_specimen"]
    assert specimen["ok"] is True
    assert specimen["role"] == "historical_short_specimen"
    assert specimen["path"] == "docs/progress/soak_2h/metrics.json"
    assert specimen["classification"] == "SHORT"
    assert specimen["experiment"] == "UBUNTU-24H"
    assert specimen["sha_short"] == "aaf8d24"
    assert specimen["wall_elapsed_s"] == 86400.001
    assert specimen["max_wall_seconds"] == 86400
    assert specimen["wall_required_seconds"] == 259200
    assert specimen["below_259200"] is True
    assert specimen["ubuntu_24h_counts_as_72h"] is False
    assert specimen["counts_toward_72h_gate"] is False
    assert specimen["ubuntu_24h_used_as_dut"] is False
    assert specimen["is_stall_dut"] is False
    assert specimen["is_l2_2_acceptance"] is False
    assert specimen["binds_clock_start"] is False
    assert specimen["wrapped_as_started_capture"] is False
    assert specimen["l2_2_status"] == "NOT_STARTED"
    assert specimen["clock_state"] == "NOT_STARTED"
    assert specimen["clock_effect"] == "none"
    assert specimen["soak_launched"] is False
    assert specimen["can_start_clock"] is False
    assert specimen["can_accept_l2_2"] is False
    assert specimen["can_close_l2_2"] is False
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["not_started_scaffold_intact"] is True
    blob = json.dumps(report)
    assert '"clock_state": "SHORT"' not in blob
    assert '"l2_2_status": "INCOMPLETE"' not in blob
    assert '"l2_2_status": "PASS"' not in blob
    assert '"can_start_clock": true' not in blob
    assert metrics_path.read_bytes() == before
    assert summary_path.read_bytes() == summary_before


def test_relabelled_ubuntu_metrics_fail_closed_without_starting(tmp_path: Path):
    metrics_path = ROOT / "docs" / "progress" / "soak_2h" / "metrics.json"
    before = metrics_path.read_bytes()
    metrics = json.loads(before)
    metrics["wall_elapsed_s"] = 259200
    metrics["max_wall_seconds"] = 259200
    copy = tmp_path / "metrics.json"
    copy.write_text(json.dumps(metrics), encoding="utf-8")
    report = pre.preflight(metrics_path=copy)
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is False
    specimen = report["ubuntu_24h_specimen"]
    assert specimen == report["checks"]["ubuntu_24h_specimen"]
    assert specimen["ok"] is False
    assert specimen["classification"] == "withheld"
    assert specimen["detail"] == "refused_as_72h"
    assert specimen["wall_elapsed_s"] is None
    assert specimen["below_259200"] is False
    assert specimen["ubuntu_24h_counts_as_72h"] is False
    assert specimen["counts_toward_72h_gate"] is False
    assert specimen["ubuntu_24h_used_as_dut"] is False
    assert specimen["is_stall_dut"] is False
    assert specimen["is_l2_2_acceptance"] is False
    assert specimen["binds_clock_start"] is False
    assert specimen["l2_2_status"] == "NOT_STARTED"
    assert specimen["clock_state"] == "NOT_STARTED"
    assert "ubuntu_24h_specimen:refused_as_72h" in report["failures"]
    blob = json.dumps(report)
    assert '"clock_state": "SHORT"' not in blob
    assert '"l2_2_status": "INCOMPLETE"' not in blob
    assert '"l2_2_status": "PASS"' not in blob
    assert '"production_7x24": "ACCEPTED"' not in blob
    assert metrics_path.read_bytes() == before


def test_forged_ubuntu_specimen_report_fails_closed():
    report = pre.preflight()
    _assert_not_a_start(report)

    def forge(**edits: object) -> dict:
        forged = json.loads(json.dumps(report))
        for key, value in edits.items():
            forged["checks"]["ubuntu_24h_specimen"][key] = value
            forged["ubuntu_24h_specimen"][key] = value
        return forged

    assert "ubuntu_24h_as_72h" in pre.validate_report(
        forge(classification="72h", ubuntu_24h_counts_as_72h=True, counts_toward_72h_gate=True)
    )
    assert "ubuntu_24h_as_72h" in pre.validate_report(
        forge(wall_elapsed_s=259200.0, below_259200=False, classification="WALL_OBSERVED")
    )
    assert "ubuntu_24h_as_dut" in pre.validate_report(
        forge(ubuntu_24h_used_as_dut=True, is_stall_dut=True)
    )
    assert "ubuntu_24h_as_acceptance" in pre.validate_report(forge(is_l2_2_acceptance=True, classification="ACCEPTED"))
    assert "ubuntu_24h_as_start" in pre.validate_report(
        forge(binds_clock_start=True, wrapped_as_started_capture=True, classification="STARTED")
    )
    names = pre.validate_report(forge(l2_2_status="PASS", classification="PASS", can_start_clock=True))
    assert "status" in names
    assert "forged_can_start_clock" in names
    assert "clock_state" in pre.validate_report(forge(clock_state="STARTED"))
    assert "production_claim" in pre.validate_report(forge(production_7x24="ACCEPTED"))
    mismatched = json.loads(json.dumps(report))
    mismatched["checks"]["ubuntu_24h_specimen"]["ubuntu_24h_used_as_dut"] = True
    mismatch_names = pre.validate_report(mismatched)
    assert "ubuntu_24h_as_dut" in mismatch_names
    assert "ubuntu_24h_specimen_mismatch" in mismatch_names
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["gates"]["can_start_clock"] is False
    assert report["ubuntu_24h_specimen"]["classification"] == "SHORT"


def test_historical_shorts_are_not_additive_and_the_clock_stays_not_started():
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is True
    assert report["documented_soak_argv_executed"] is False
    assert report["clock_effect"] == "none"
    row = report["non_additivity"]
    assert row == report["checks"]["non_additivity"]
    assert row["ok"] is True
    assert row["detail"] == "shorts_not_additive"
    assert row["rule"] == "one_continuous_monotonic_wall"
    assert row["tool"] == "scripts/l2_2_score.py"
    assert row["historical_shorts_are_additive"] is False
    assert row["sum_of_shorts_counts_toward_gate"] is False
    assert row["d1_windows_metrics_file"] is None
    assert row["d1_windows_bound_as_specimen"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["clock_effect"] == "none"
    assert row["soak_launched"] is False
    assert row["binds_clock_start"] is False
    assert row["documented_soak_argv_executed"] is False
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    known = row["known_committed_shorts"]
    assert len(known) == 1
    assert known[0]["id"] == "ubuntu_24h"
    assert known[0]["path"] == "docs/progress/soak_2h/metrics.json"
    assert known[0]["wall_elapsed_s"] == 86400.001
    assert known[0]["counts_toward_gate"] is False
    assert known[0]["committed_metrics_file"] is True
    by_label = {item["label"]: item for item in row["refused_sums"]}
    assert set(by_label) == {
        "ubuntu_24h_alone",
        "ubuntu_24h_plus_another_86400",
        "three_times_86400",
        "ubuntu_24h_plus_two_86400",
    }
    assert by_label["ubuntu_24h_alone"]["sum_seconds"] == 86400.001
    assert by_label["ubuntu_24h_alone"]["naive_sum_reaches_259200"] is False
    assert by_label["ubuntu_24h_plus_another_86400"]["sum_seconds"] == 172800.001
    assert by_label["ubuntu_24h_plus_another_86400"]["components_seconds"] == [86400.001, 86400.0]
    assert by_label["ubuntu_24h_plus_another_86400"]["naive_sum_reaches_259200"] is False
    assert by_label["three_times_86400"]["sum_seconds"] == 259200.0
    assert by_label["three_times_86400"]["components_seconds"] == [86400.0, 86400.0, 86400.0]
    assert by_label["three_times_86400"]["naive_sum_reaches_259200"] is True
    assert by_label["ubuntu_24h_plus_two_86400"]["sum_seconds"] == 259200.001
    assert by_label["ubuntu_24h_plus_two_86400"]["naive_sum_reaches_259200"] is True
    for item in by_label.values():
        assert item["counts_toward_gate"] is False
        assert item["historical_shorts_are_additive"] is False
        assert item["continuous_monotonic_wall"] is False
        assert item["single_live_soak"] is False
        assert item["wall_required_seconds"] == 259200
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    blob = json.dumps(report)
    assert '"historical_shorts_are_additive": true' not in blob
    assert '"sum_of_shorts_counts_toward_gate": true' not in blob
    assert '"counts_toward_gate": true' not in blob
    assert '"l2_2_status": "PASS"' not in blob
    assert '"clock_state": "WALL_OBSERVED"' not in blob


def test_forged_additive_preflight_fails_closed():
    report = pre.preflight()
    _assert_not_a_start(report)
    forged = json.loads(json.dumps(report))
    forged["non_additivity"]["historical_shorts_are_additive"] = True
    forged["non_additivity"]["sum_of_shorts_counts_toward_gate"] = True
    forged["non_additivity"]["l2_2_status"] = "PASS"
    forged["non_additivity"]["clock_state"] = "STARTED"
    forged["non_additivity"]["production_7x24"] = "ACCEPTED"
    forged["non_additivity"]["can_start_clock"] = True
    forged["non_additivity"]["binds_clock_start"] = True
    forged["checks"]["non_additivity"] = json.loads(json.dumps(forged["non_additivity"]))
    for item in forged["non_additivity"]["refused_sums"]:
        if item["label"] == "three_times_86400":
            item["counts_toward_gate"] = True
            item["historical_shorts_are_additive"] = True
            item["continuous_monotonic_wall"] = True
    for item in forged["checks"]["non_additivity"]["refused_sums"]:
        if item["label"] == "three_times_86400":
            item["counts_toward_gate"] = True
            item["historical_shorts_are_additive"] = True
            item["continuous_monotonic_wall"] = True
    names = set(pre.validate_report(forged))
    assert "additive_historical_shorts" in names
    assert "status" in names
    assert "clock_state" in names
    assert "production_claim" in names
    assert "forged_can_start_clock" in names
    assert "additive_as_start" in names
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["gates"]["can_start_clock"] is False
    assert report["non_additivity"]["historical_shorts_are_additive"] is False
    assert report["documented_soak_argv_executed"] is False


def test_sequential_soaks_do_not_stitch_into_72h_and_the_clock_stays_not_started():
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is True
    assert report["documented_soak_argv_executed"] is False
    assert report["clock_effect"] == "none"
    row = report["process_continuity"]
    assert row == report["checks"]["process_continuity"]
    assert row["ok"] is True
    assert row["detail"] == "stitches_not_continuous"
    assert row["rule"] == "one_live_soak_process"
    assert row["tool"] == "scripts/l2_2_score.py"
    assert row["sequential_soaks_are_continuous"] is False
    assert row["stitched_processes_count_toward_gate"] is False
    assert row["counts_toward_gate"] is False
    assert row["d1_windows_metrics_file"] is None
    assert row["d1_windows_bound_as_specimen"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["clock_effect"] == "none"
    assert row["soak_launched"] is False
    assert row["binds_clock_start"] is False
    assert row["documented_soak_argv_executed"] is False
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    by_label = {item["label"]: item for item in row["refused_stitches"]}
    assert list(by_label) == [
        "pair_86400_back_to_back",
        "trio_86400_calendar_72h",
        "wall_reset_three_86400",
    ]
    pair = by_label["pair_86400_back_to_back"]
    assert pair["walls_seconds"] == [86400.0, 86400.0]
    assert pair["stitched_duration_seconds"] == 172800.0
    assert pair["calendar_span_seconds"] == 172800.0
    assert pair["same_host"] is True
    assert pair["back_to_back"] is True
    assert pair["distinct_start_count"] == 2
    assert pair["distinct_process_count"] == 2
    assert pair["stitched_duration_reaches_259200"] is False
    trio = by_label["trio_86400_calendar_72h"]
    assert trio["walls_seconds"] == [86400.0, 86400.0, 86400.0]
    assert trio["stitched_duration_seconds"] == 259200.0
    assert trio["calendar_span_seconds"] == 259200.0
    assert trio["stitched_duration_reaches_259200"] is True
    assert trio["calendar_span_reaches_259200"] is True
    assert trio["same_host"] is True
    reset = by_label["wall_reset_three_86400"]
    assert reset["wall_reset"] is True
    assert reset["segment_count"] == 3
    assert reset["stitched_duration_seconds"] == 259200.0
    assert reset["stitched_duration_reaches_259200"] is True
    assert reset["calendar_span_reaches_259200"] is False
    for item in by_label.values():
        assert item["counts_toward_gate"] is False
        assert item["sequential_soaks_are_continuous"] is False
        assert item["stitched_processes_count_toward_gate"] is False
        assert item["single_live_process"] is False
        assert item["wall_required_seconds"] == 259200
    assert report["ubuntu_24h_specimen"]["ubuntu_24h_counts_as_72h"] is False
    assert report["ubuntu_24h_specimen"]["ubuntu_24h_used_as_dut"] is False
    assert report["ubuntu_24h_specimen"]["classification"] == "SHORT"
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    blob = json.dumps(report)
    assert '"sequential_soaks_are_continuous": true' not in blob
    assert '"stitched_processes_count_toward_gate": true' not in blob
    assert '"counts_toward_gate": true' not in blob
    assert '"l2_2_status": "PASS"' not in blob
    assert '"clock_state": "WALL_OBSERVED"' not in blob
    readme = (ROOT / "docs" / "progress" / "l2_2" / "README.md").read_text(encoding="utf-8")
    decision = (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md").read_text(encoding="utf-8")
    assert "process-boundary continuity" in readme
    assert "not a start" in readme
    assert "The offline process-boundary continuity gate is not a start." in decision
    assert pre.classify_start_decision(decision)["start_decision"] == "not_given"
    assert "Stitching sequential or restarted soak invocations" in checklist
    assert "Recording that rule is not a start." in checklist
    assert pre.classify_r2(checklist)["start_decision"] == "not_given"


def test_forged_stitch_preflight_fails_closed():
    report = pre.preflight()
    _assert_not_a_start(report)
    forged = json.loads(json.dumps(report))
    forged["process_continuity"]["sequential_soaks_are_continuous"] = True
    forged["process_continuity"]["stitched_processes_count_toward_gate"] = True
    forged["process_continuity"]["counts_toward_gate"] = True
    forged["process_continuity"]["l2_2_status"] = "PASS"
    forged["process_continuity"]["clock_state"] = "STARTED"
    forged["process_continuity"]["production_7x24"] = "ACCEPTED"
    forged["process_continuity"]["can_start_clock"] = True
    forged["process_continuity"]["binds_clock_start"] = True
    forged["checks"]["process_continuity"] = json.loads(json.dumps(forged["process_continuity"]))
    for item in forged["process_continuity"]["refused_stitches"]:
        if item["label"] == "trio_86400_calendar_72h":
            item["counts_toward_gate"] = True
            item["sequential_soaks_are_continuous"] = True
            item["stitched_processes_count_toward_gate"] = True
    for item in forged["checks"]["process_continuity"]["refused_stitches"]:
        if item["label"] == "trio_86400_calendar_72h":
            item["counts_toward_gate"] = True
            item["sequential_soaks_are_continuous"] = True
            item["stitched_processes_count_toward_gate"] = True
    names = set(pre.validate_report(forged))
    assert "stitched_process_boundaries" in names
    assert "status" in names
    assert "clock_state" in names
    assert "production_claim" in names
    assert "forged_can_start_clock" in names
    assert "stitch_as_start" in names
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["clock_effect"] == "none"
    assert report["gates"]["can_start_clock"] is False
    assert report["process_continuity"]["sequential_soaks_are_continuous"] is False
    assert report["process_continuity"]["stitched_processes_count_toward_gate"] is False
    assert report["documented_soak_argv_executed"] is False


def test_founder_approval_is_recorded_and_is_not_a_start():
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is True
    row = report["founder_start_conditions"]
    assert row == report["checks"]["founder_start_conditions"]
    assert row["ok"] is True
    assert row["detail"] == "approval_recorded_not_a_start"
    assert row["rule"] == "five_founder_conditions_before_start"
    assert row["approval_exists"] is True
    assert row["approval_conditional"] is True
    assert row["approval_issue"] == 9
    assert row["approval_comment_id"] == 6761044915
    assert row["approval_utc"] == "2026-11-10T06:50:14Z"
    assert row["approval_target_pr"] == 12
    assert row["approval_is_a_start"] is False
    assert row["approval_is_a_pass"] is False
    assert row["approval_without_conditions_is_a_start"] is False
    assert row["approval_without_start_registration_is_a_start"] is False
    assert row["start_registration_present"] is False
    assert row["start_registration_posted_to_issue_9"] is False
    assert row["conditions_satisfied"] is False
    assert row["missing_conditions"] == list(l2.FOUNDER_CONDITION_IDS)
    assert row["templates_unfilled"] is True
    assert row["blank_template_documents_bands"] is True
    assert row["local_only_counts_as_public_evidence"] is False
    assert row["unknown_root_cause_allowed"] is False
    assert row["soak_dut_watchdog_counts_as_supervisor_watchdog"] is False
    assert row["soak_dut_watchdog_tool"] == "scripts/stall_watchdog.py"
    assert row["a_72h_pass_is_production_readiness"] is False
    assert row["declarations_are_not_a_start"] is True
    assert row["can_start_clock"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["clock_effect"] == "none"
    assert row["soak_launched"] is False
    assert row["production_7x24"] == "NOT_ACCEPTED"
    labels = [item["label"] for item in row["refused_claims"]]
    assert labels == [
        "approval_is_not_a_start",
        "missing_condition",
        "local_only",
        "unknown_root_cause",
        "supervisor_without_watchdog",
        "soak_dut_watchdog_substituted",
    ]
    by_label = {item["label"]: item for item in row["refused_claims"]}
    assert by_label["approval_is_not_a_start"]["approval_claimed_as_start"] is True
    assert by_label["approval_is_not_a_start"]["approval_is_a_start"] is False
    assert by_label["approval_is_not_a_start"]["conditions_satisfied"] is False
    assert by_label["approval_is_not_a_start"]["counts_as_start"] is False
    assert by_label["missing_condition"]["missing_conditions"] == ["supervision_policy"]
    assert by_label["missing_condition"]["conditions_satisfied"] is False
    assert by_label["local_only"]["local_only_refused"] is True
    assert by_label["local_only"]["local_only_counts_as_public_evidence"] is False
    assert by_label["local_only"]["condition_detail"] == "local_only_refused"
    assert by_label["unknown_root_cause"]["unknown_root_cause_refused"] is True
    assert by_label["unknown_root_cause"]["unknown_root_cause_allowed"] is False
    assert by_label["supervisor_without_watchdog"]["condition_detail"] == "supervisor_watchdog_missing"
    assert by_label["supervisor_without_watchdog"]["supervisor_watchdog_refused"] is True
    assert by_label["soak_dut_watchdog_substituted"]["condition_detail"] == "soak_dut_watchdog_is_not_supervisor_watchdog"
    assert by_label["soak_dut_watchdog_substituted"]["soak_dut_watchdog_counts_as_supervisor_watchdog"] is False
    for item in row["refused_claims"]:
        assert item["can_start_clock"] is False
        assert item["counts_as_start"] is False
        assert item["counts_as_pass"] is False
        assert item["l2_2_status"] == "NOT_STARTED"
        assert item["production_7x24"] == "NOT_ACCEPTED"
    decision = (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md").read_text(encoding="utf-8")
    readme = (ROOT / "docs" / "progress" / "l2_2" / "README.md").read_text(encoding="utf-8")
    assert "6761044915" in decision
    assert "6761044915" in checklist
    assert "6761044915" in readme
    assert "not a start" in decision.lower() or "is not a start" in decision
    assert pre.classify_start_decision(decision)["start_decision"] == "not_given"
    assert pre.classify_start_decision(decision)["ok"] is True
    assert pre.classify_r2(checklist)["start_decision"] == "not_given"
    assert l2.start_registration_line_present(decision) is False
    assert l2.start_registration_line_present(checklist) is False
    assert "LOCAL_ONLY does not count" in decision
    assert "Unknown root cause is not a terminal attribution" in decision
    assert "stall_watchdog.py" in decision
    blob = json.dumps(report)
    assert '"approval_is_a_start": true' not in blob
    assert '"conditions_satisfied": true' not in blob
    assert '"can_start_clock": true' not in blob
    assert '"l2_2_status": "PASS"' not in blob
    assert '"production_7x24": "ACCEPTED"' not in blob
    assert "conditional founder approval" in report["operator_note"]
    assert any("6761044915" in step and "not a start" in step for step in report["next_steps"])


def test_forged_founder_preflight_fails_closed():
    report = pre.preflight()
    _assert_not_a_start(report)
    forged = json.loads(json.dumps(report))
    forged["founder_start_conditions"]["approval_is_a_start"] = True
    forged["founder_start_conditions"]["conditions_satisfied"] = True
    forged["founder_start_conditions"]["start_registration_present"] = True
    forged["founder_start_conditions"]["local_only_counts_as_public_evidence"] = True
    forged["founder_start_conditions"]["unknown_root_cause_allowed"] = True
    forged["founder_start_conditions"]["soak_dut_watchdog_counts_as_supervisor_watchdog"] = True
    forged["founder_start_conditions"]["a_72h_pass_is_production_readiness"] = True
    forged["founder_start_conditions"]["can_start_clock"] = True
    forged["founder_start_conditions"]["l2_2_status"] = "PASS"
    forged["founder_start_conditions"]["clock_state"] = "STARTED"
    forged["founder_start_conditions"]["production_7x24"] = "ACCEPTED"
    forged["checks"]["founder_start_conditions"] = json.loads(json.dumps(forged["founder_start_conditions"]))
    names = set(pre.validate_report(forged))
    assert "approval_is_not_a_start" in names
    assert "founder_conditions_missing" in names
    assert "local_only_refused" in names
    assert "unknown_root_cause_refused" in names
    assert "supervisor_watchdog_required" in names
    assert "production_claim" in names
    assert "status" in names
    assert "forged_can_start_clock" in names
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["gates"]["can_start_clock"] is False
    assert report["founder_start_conditions"]["approval_is_a_start"] is False
    assert report["founder_start_conditions"]["conditions_satisfied"] is False
    assert report["documented_soak_argv_executed"] is False


def test_filled_start_registration_line_is_not_this_pass(tmp_path: Path):
    original = (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")
    path = tmp_path / "START_DECISION.md"
    line = (
        "L2-2 START: utc=2026-02-01T00:00:00Z "
        "sha=0123456789abcdef0123456789abcdef01234567 "
        "host=example max_wall_seconds=259200\n"
    )
    path.write_text(original + "\n" + line, encoding="utf-8")
    assert l2.start_registration_line_present(path.read_text(encoding="utf-8")) is True
    assert l2.start_registration_line_present(original) is False
    report = pre.preflight(start_decision_path=path)
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is False
    founder = report["checks"]["founder_start_conditions"]
    assert founder["ok"] is False
    assert founder["detail"] == "start_registration_is_not_this_pass"
    assert founder["start_registration_present"] is False
    assert founder["start_registration_posted_to_issue_9"] is False
    assert founder["approval_is_a_start"] is False
    assert founder["conditions_satisfied"] is False
    assert founder["can_start_clock"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert "founder_start_conditions:start_registration_is_not_this_pass" in report["failures"]
    assert original == (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")


def test_supervisor_watchdog_probe_is_recorded_and_is_not_a_start():
    report = pre.preflight()
    _assert_not_a_start(report)
    assert report["not_started_scaffold_intact"] is True
    row = report["supervisor_watchdog_honesty"]
    assert row == report["checks"]["supervisor_watchdog_honesty"]
    assert row["ok"] is True
    assert row["detail"] == "synthetic_alive_vs_crash_unrecorded"
    assert row["dut"] == "synthetic_temp_supervisor"
    assert row["tool"] == "scripts/l2_2_score.py"
    assert row["soak_dut_watchdog_tool"] == "scripts/stall_watchdog.py"
    assert row["condition_2_satisfied"] is False
    assert row["offline_probe_satisfies_condition_2"] is False
    assert row["offline_probe_is_supervisor_watchdog"] is False
    assert row["is_supervisor_watchdog_of_live_supervisor"] is False
    assert row["soak_dut_stall_watchdog_is_supervisor_watchdog"] is False
    assert row["is_a_start"] is False
    assert row["live_supervisor_process"] is False
    assert row["live_soak_process"] is False
    assert row["soak_launched"] is False
    assert row["can_start_clock"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    labels = [item["label"] for item in row["cases"]]
    assert labels == [
        "supervisor_alive",
        "supervisor_crash_unrecorded",
        "supervisor_crash_record_too_slow",
    ]
    claim_labels = [item["label"] for item in row["refused_claims"]]
    assert claim_labels == [
        "soak_dut_stall_watchdog_substituted",
        "offline_probe_substituted",
        "condition_2_and_pass_claimed",
    ]
    by_label = {item["label"]: item for item in row["refused_claims"]}
    assert by_label["soak_dut_stall_watchdog_substituted"]["stall_watchdog_claimed_as_supervisor_watchdog"] is True
    assert by_label["soak_dut_stall_watchdog_substituted"]["condition_2_satisfied"] is False
    assert by_label["offline_probe_substituted"]["offline_probe_claimed_as_supervisor_watchdog"] is True
    assert by_label["offline_probe_substituted"]["offline_probe_is_supervisor_watchdog"] is False
    assert by_label["condition_2_and_pass_claimed"]["condition_2_claimed_satisfied"] is True
    assert by_label["condition_2_and_pass_claimed"]["pass_or_start_claimed"] is True
    assert by_label["condition_2_and_pass_claimed"]["l2_2_status"] == "NOT_STARTED"
    assert by_label["condition_2_and_pass_claimed"]["production_7x24"] == "NOT_ACCEPTED"
    for item in row["refused_claims"]:
        assert item["can_start_clock"] is False
        assert item["is_a_start"] is False
        assert item["condition_2_satisfied"] is False
    assert "does not satisfy founder condition 2" in report["operator_note"]
    assert any("founder condition 2" in step and "not a start" in step for step in report["next_steps"])
    blob = json.dumps(report)
    assert '"condition_2_satisfied": true' not in blob
    assert '"offline_probe_is_supervisor_watchdog": true' not in blob
    assert '"can_start_clock": true' not in blob
    assert '"l2_2_status": "PASS"' not in blob
    assert '"production_7x24": "ACCEPTED"' not in blob


def test_forged_supervisor_watchdog_preflight_fails_closed():
    report = pre.preflight()
    _assert_not_a_start(report)
    forged = json.loads(json.dumps(report))
    forged["supervisor_watchdog_honesty"]["condition_2_satisfied"] = True
    forged["supervisor_watchdog_honesty"]["offline_probe_satisfies_condition_2"] = True
    forged["supervisor_watchdog_honesty"]["offline_probe_is_supervisor_watchdog"] = True
    forged["supervisor_watchdog_honesty"]["soak_dut_stall_watchdog_is_supervisor_watchdog"] = True
    forged["supervisor_watchdog_honesty"]["tool"] = "scripts/stall_watchdog.py"
    forged["supervisor_watchdog_honesty"]["l2_2_status"] = "PASS"
    forged["supervisor_watchdog_honesty"]["clock_state"] = "STARTED"
    forged["supervisor_watchdog_honesty"]["production_7x24"] = "ACCEPTED"
    forged["supervisor_watchdog_honesty"]["can_start_clock"] = True
    forged["supervisor_watchdog_honesty"]["is_a_start"] = True
    forged["checks"]["supervisor_watchdog_honesty"] = json.loads(json.dumps(forged["supervisor_watchdog_honesty"]))
    names = set(pre.validate_report(forged))
    assert "condition_2_unsatisfied" in names
    assert "offline_probe_is_not_supervisor_watchdog" in names
    assert "supervisor_watchdog_required" in names
    assert "forged_pass" in names
    assert "production_claim" in names
    assert "forged_can_start_clock" in names
    assert "offline_probe_is_not_a_start" in names
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["gates"]["can_start_clock"] is False
    assert report["supervisor_watchdog_honesty"]["condition_2_satisfied"] is False
    assert report["documented_soak_argv_executed"] is False


def test_dummy_supervisor_watchdog_is_recorded_and_is_not_condition_2():
    report = pre.preflight()
    _assert_not_a_start(report)
    row = report["supervisor_watchdog_implementation"]
    assert row == report["checks"]["supervisor_watchdog_implementation"]
    assert row["ok"] is True
    assert row["detail"] == "implementation_exists_dummy_crash_within_10s_passed"
    assert row["tool"] == "scripts/supervisor_watchdog.py"
    assert row["dummy_crash_within_10s_passed"] is True
    assert row["dummy_still_alive_wrote_no_crash_record"] is True
    assert row["record_11s_later_meets_requirement"] is False
    assert row["condition_2_satisfied"] is False
    assert row["dummy_tests_satisfy_condition_2"] is False
    assert row["scaffold_satisfies_condition_2"] is False
    assert row["is_live_l2_2_supervisor_watchdog"] is False
    assert row["demonstrates_10_minute_supervision_cadence"] is False
    assert row["live_supervisor_process"] is False
    assert row["soak_launched"] is False
    assert row["can_start_clock"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    labels = [item["label"] for item in row["refused_claims"]]
    assert labels == [
        "dummy_scaffold_called_condition_2",
        "synthetic_probe_called_condition_2",
        "stall_watchdog_called_condition_2",
    ]
    for item in row["refused_claims"]:
        assert item["condition_2_satisfied"] is False
        assert item["can_start_clock"] is False
        assert item["l2_2_status"] == "NOT_STARTED"
    forged = json.loads(json.dumps(report))
    forged["supervisor_watchdog_implementation"]["condition_2_satisfied"] = True
    forged["supervisor_watchdog_implementation"]["dummy_tests_satisfy_condition_2"] = True
    forged["supervisor_watchdog_implementation"]["l2_2_status"] = "PASS"
    forged["supervisor_watchdog_implementation"]["clock_state"] = "STARTED"
    forged["supervisor_watchdog_implementation"]["can_start_clock"] = True
    forged["checks"]["supervisor_watchdog_implementation"] = json.loads(
        json.dumps(forged["supervisor_watchdog_implementation"])
    )
    names = set(pre.validate_report(forged))
    assert "condition_2_unsatisfied" in names
    assert "forged_pass" in names
    assert "forged_can_start_clock" in names
    assert report["supervisor_watchdog_implementation"]["condition_2_satisfied"] is False
    assert report["gates"]["can_start_clock"] is False


def test_short_cadence_exercise_is_recorded_and_is_not_condition_2():
    report = pre.preflight()
    _assert_not_a_start(report)
    row = report["supervision_cadence_writer"]
    assert row == report["checks"]["supervision_cadence_writer"]
    assert row["ok"] is True
    assert row["detail"] == "implementation_exists_short_interval_writes_on_schedule"
    assert row["tool"] == "scripts/supervision_cadence.py"
    assert row["action"] == "time_compressed_offline_writes"
    assert row["time_compressed"] is True
    assert row["simulated_clock"] is False
    assert row["writes_on_schedule_passed"] is True
    assert row["exercise_interval_seconds"] == 0.2
    assert row["production_max_seconds"] == 600
    assert row["late_gap_seconds"] == 601
    assert row["late_write_meets_cadence"] is False
    assert row["bound_gap_within_numeric_bound"] is True
    assert row["condition_2_satisfied"] is False
    assert row["demonstrates_10_minute_supervision_cadence"] is False
    assert row["is_supervisor_watchdog_of_live_supervisor"] is False
    assert row["is_live_l2_2_supervisor"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["soak_launched"] is False
    labels = [item["label"] for item in row["refused_claims"]]
    assert labels == [
        "time_compressed_called_10_minute_cadence",
        "offline_exercise_called_condition_2",
        "stall_watchdog_called_cadence_writer",
        "crash_watchdog_called_cadence_writer",
    ]
    for item in row["refused_claims"]:
        assert item["condition_2_satisfied"] is False
        assert item["demonstrates_10_minute_supervision_cadence"] is False
        assert item["can_start_clock"] is False
    forged = json.loads(json.dumps(report))
    forged["supervision_cadence_writer"]["demonstrates_10_minute_supervision_cadence"] = True
    forged["supervision_cadence_writer"]["condition_2_satisfied"] = True
    forged["supervision_cadence_writer"]["can_start_clock"] = True
    forged["supervision_cadence_writer"]["l2_2_status"] = "PASS"
    forged["checks"]["supervision_cadence_writer"] = json.loads(json.dumps(forged["supervision_cadence_writer"]))
    names = set(pre.validate_report(forged))
    assert "condition_2_unsatisfied" in names
    assert "forged_can_start_clock" in names
    assert "forged_pass" in names
    assert report["supervision_cadence_writer"]["demonstrates_10_minute_supervision_cadence"] is False
    assert report["gates"]["can_start_clock"] is False
    assert '"demonstrates_10_minute_supervision_cadence": true' not in json.dumps(report)


def test_sample_failure_attribution_is_recorded_and_is_not_condition_4():
    report = pre.preflight()
    _assert_not_a_start(report)
    row = report["failure_attribution"]
    assert row == report["checks"]["failure_attribution"]
    assert row["ok"] is True
    assert row["detail"] == "implementation_exists_sample_attributions_classified"
    assert row["tool"] == "scripts/failure_attribution.py"
    assert row["action"] == "classify_sample_records"
    assert row["dut"] == "synthetic_attribution_records"
    assert row["classifies_sample_attributions_passed"] is True
    assert row["unknown_root_cause_rejected"] is True
    assert row["empty_root_cause_rejected"] is True
    assert row["missing_root_cause_rejected"] is True
    assert row["free_text_root_cause_rejected"] is True
    assert row["multiple_classes_rejected"] is True
    assert row["condition_4_satisfied"] is False
    assert row["attributes_live_soak_failure"] is False
    assert row["dummy_tests_satisfy_condition_4"] is False
    assert row["implementation_satisfies_condition_4"] is False
    assert row["condition_2_satisfied"] is False
    assert row["demonstrates_10_minute_supervision_cadence"] is False
    assert row["is_supervisor_watchdog_of_live_supervisor"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["soak_launched"] is False
    classes = {item["terminal_class"] for item in row["samples"] if item["accepted"] is True}
    assert classes == {"business", "host", "supervision"}
    rejected = {item["id"]: item["rejection"] for item in row["samples"] if item["accepted"] is False}
    assert rejected["unknown_label"] == "unknown"
    assert rejected["empty_terminal"] == "empty"
    assert rejected["missing_record"] == "missing"
    assert rejected["multiple_classes_without_terminal"] == "multiple_classes"
    labels = [item["label"] for item in row["refused_claims"]]
    assert labels == [
        "sample_classification_called_condition_4",
        "unknown_root_cause_called_terminal",
        "multiple_classes_called_single_terminal",
        "sample_called_live_soak_attribution",
    ]
    for item in row["refused_claims"]:
        assert item["condition_4_satisfied"] is False
        assert item["attributes_live_soak_failure"] is False
        assert item["can_start_clock"] is False
        assert item["l2_2_status"] == "NOT_STARTED"
    assert "does not satisfy founder condition 4" in report["operator_note"]
    assert any("founder condition 4" in step and "not a start" in step for step in report["next_steps"])
    blob = json.dumps(report)
    assert '"condition_4_satisfied": true' not in blob
    assert '"attributes_live_soak_failure": true' not in blob
    assert '"can_start_clock": true' not in blob
    forged = json.loads(blob)
    forged["failure_attribution"]["condition_4_satisfied"] = True
    forged["failure_attribution"]["attributes_live_soak_failure"] = True
    forged["failure_attribution"]["can_start_clock"] = True
    forged["failure_attribution"]["l2_2_status"] = "PASS"
    forged["checks"]["failure_attribution"] = json.loads(json.dumps(forged["failure_attribution"]))
    names = set(pre.validate_report(forged))
    assert "condition_4_unsatisfied" in names
    assert "forged_can_start_clock" in names
    assert "forged_pass" in names
    assert report["failure_attribution"]["condition_4_satisfied"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"


def test_sample_public_pack_is_recorded_and_is_not_condition_3():
    report = pre.preflight()
    _assert_not_a_start(report)
    row = report["public_evidence_pack"]
    assert row == report["checks"]["public_evidence_pack"]
    assert row["ok"] is True
    assert row["detail"] == "implementation_exists_sample_public_pack_validated"
    assert row["tool"] == "scripts/public_evidence_pack.py"
    assert row["action"] == "validate_sample_public_pack"
    assert row["dut"] == "synthetic_sample_public_pack"
    assert row["hasher"] == "scripts/evidence_sha256sums.py"
    assert row["sample_only"] is True
    assert row["offline"] is True
    assert row["classifies_or_validates_sample_public_pack_passed"] is True
    assert row["local_only_pack_rejected"] is True
    assert row["missing_piece_rejected"] is True
    assert row["scaffold_sha256sums_refused"] is True
    assert row["committed_scaffold_sums_refused"] is True
    assert row["condition_3_satisfied"] is False
    assert row["packs_live_soak_evidence"] is False
    assert row["dummy_tests_satisfy_condition_3"] is False
    assert row["implementation_satisfies_condition_3"] is False
    assert row["local_only_counts_as_public_evidence"] is False
    assert row["scaffold_sha256sums_is_soak_evidence"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["soak_launched"] is False
    by_id = {item["id"]: item for item in row["samples"]}
    assert by_id["sample_public_complete"]["accepted"] is True
    assert by_id["local_only_with_all_pieces"]["rejection"] == "local_only"
    assert by_id["local_only_with_all_pieces"]["local_only_pack_rejected"] is True
    assert by_id["missing_final_metrics"]["rejection"] == "missing_final_metrics"
    assert by_id["missing_log_summary"]["rejection"] == "missing_log_summary"
    assert by_id["missing_sha_list"]["rejection"] == "missing_sha_list"
    assert by_id["scaffold_sha256sums"]["rejection"] == "scaffold_sha256sums_not_soak_evidence"
    assert by_id["scaffold_sha256sums"]["scaffold_sha256sums_is_soak_evidence"] is False
    labels = [item["label"] for item in row["refused_claims"]]
    assert labels == [
        "sample_pack_called_condition_3",
        "local_only_called_public_evidence",
        "scaffold_sha256sums_called_soak_evidence",
        "sample_called_live_soak_pack",
    ]
    for item in row["refused_claims"]:
        assert item["condition_3_satisfied"] is False
        assert item["packs_live_soak_evidence"] is False
        assert item["local_only_counts_as_public_evidence"] is False
        assert item["scaffold_sha256sums_is_soak_evidence"] is False
        assert item["can_start_clock"] is False
        assert item["l2_2_status"] == "NOT_STARTED"
    assert "does not satisfy founder condition 3" in report["operator_note"]
    assert any("founder condition 3" in step and "not a start" in step for step in report["next_steps"])
    blob = json.dumps(report)
    assert '"condition_3_satisfied": true' not in blob
    assert '"packs_live_soak_evidence": true' not in blob
    assert '"scaffold_sha256sums_is_soak_evidence": true' not in blob
    assert '"can_start_clock": true' not in blob
    forged = json.loads(blob)
    forged["public_evidence_pack"]["condition_3_satisfied"] = True
    forged["public_evidence_pack"]["packs_live_soak_evidence"] = True
    forged["public_evidence_pack"]["scaffold_sha256sums_is_soak_evidence"] = True
    forged["public_evidence_pack"]["can_start_clock"] = True
    forged["public_evidence_pack"]["l2_2_status"] = "PASS"
    forged["checks"]["public_evidence_pack"] = json.loads(json.dumps(forged["public_evidence_pack"]))
    names = set(pre.validate_report(forged))
    assert "condition_3_unsatisfied" in names
    assert "scaffold_sha256sums_not_soak_evidence" in names
    assert "forged_can_start_clock" in names
    assert "forged_pass" in names
    assert report["public_evidence_pack"]["condition_3_satisfied"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
