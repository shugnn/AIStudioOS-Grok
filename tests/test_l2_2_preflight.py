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


def test_operator_notes_say_running_is_not_a_start():
    readme = (ROOT / "docs" / "progress" / "l2_2" / "README.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md").read_text(encoding="utf-8")
    decision = (ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "docs" / "progress" / "l2_2" / "SCHEMA.json").read_text(encoding="utf-8"))
    assert "scripts/l2_2_preflight.py" in readme
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
