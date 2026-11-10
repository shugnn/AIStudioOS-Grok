"""health_check L2-2 section. Exit 0 is not a start and not acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import health_check as hc  # noqa: E402
import l2_2_preflight as pre  # noqa: E402
import l2_2_score as l2  # noqa: E402

CHECKLIST = ROOT / "docs" / "progress" / "l2_2" / "R2_CHECKLIST.md"
START_DECISION = ROOT / "docs" / "progress" / "l2_2" / "START_DECISION.md"
PREFLIGHT_JSON = ROOT / "docs" / "progress" / "l2_2" / "scaffold" / "preflight.json"
STOP = ROOT / "docs" / "progress" / "EMERGENCY_STOP"
NOT_STARTED = ROOT / "tests" / "fixtures" / "l2_2" / "scaffold_clock_not_started.json"
WALL_SHORT = ROOT / "tests" / "fixtures" / "l2_2" / "scaffold_wall_short.json"

GATE_KEYS = ("can_start_clock", "can_accept_l2_2", "can_close_l2_2")


def _honest() -> tuple[dict, dict, str]:
    preflight_report = pre.preflight()
    scored = l2.score(l2.load_capture(NOT_STARTED))
    return preflight_report, scored, CHECKLIST.read_text(encoding="utf-8")


def _assess(preflight_report: dict, scored: dict, r2_text: str, **kwargs) -> dict:
    return hc.assess_l2_2_offline(
        preflight_report,
        scored,
        r2_text=r2_text,
        preflight_exit=kwargs.get("preflight_exit", 0),
        score_exit=kwargs.get("score_exit", 0),
        start_decision_text=kwargs.get("start_decision_text"),
    )


def _assert_gates_closed(result: dict) -> None:
    assert result["soak_launched"] is False
    assert result["production_7x24"] == "NOT_ACCEPTED"
    assert result["can_start_clock"] is False
    assert result["can_accept_l2_2"] is False
    assert result["can_close_l2_2"] is False
    assert result["gate_result"] == "NOT_A_GATE"
    assert result["exit_0_is_gate_pass"] is False
    assert result["pytest_is_l2_2_acceptance"] is False
    text = json.dumps({key: result[key] for key in GATE_KEYS})
    assert "true" not in text


def test_healthy_not_started_scaffold_keeps_gates_false():
    preflight_report, scored, r2_text = _honest()
    assert preflight_report["l2_2_status"] == "NOT_STARTED"
    assert scored["l2_2_status"] == "NOT_STARTED"
    assert scored["clock_state"] == "NOT_STARTED"
    result = _assess(preflight_report, scored, r2_text)
    assert result["ok"] is True
    assert result["violations"] == []
    assert result["l2_2_status"] == "NOT_STARTED"
    assert result["clock_state"] == "NOT_STARTED"
    assert result["r2_unfilled"] is True
    assert result["start_decision_unfilled"] is True
    assert result["stall_dut"] == "synthetic_temp_summary"
    assert result["ubuntu_24h_used_as_dut"] is False
    assert result["stall_hook_is_l2_2_acceptance"] is False
    stall = preflight_report["checks"]["stall_watchdog"]
    assert stall["detail"] == "synthetic_fresh_vs_stale"
    assert stall["fresh_stalled"] is False
    assert stall["stale_stalled"] is True
    assert stall["fresh_gap_band"] == "ok"
    assert stall["stale_gap_band"] == "red"
    assert stall["ubuntu_24h_used_as_dut"] is False
    assert stall["implies_l2_2_acceptance"] is False
    assert stall["binds_clock_start"] is False
    assert stall["can_start_clock"] is False
    _assert_gates_closed(result)


def test_subprocess_preflight_and_score_stay_not_started():
    before = {
        CHECKLIST: CHECKLIST.read_bytes(),
        START_DECISION: START_DECISION.read_bytes(),
        PREFLIGHT_JSON: PREFLIGHT_JSON.read_bytes(),
        STOP: STOP.read_bytes() if STOP.exists() else None,
    }
    assert before[STOP] is None
    result = hc.run_l2_2_assessment()
    assert result["ok"] is True, result["violations"]
    assert result["l2_2_status"] == "NOT_STARTED"
    assert result["clock_state"] == "NOT_STARTED"
    assert result["r2_unfilled"] is True
    assert result["start_decision_unfilled"] is True
    assert result["stall_dut"] == "synthetic_temp_summary"
    assert result["ubuntu_24h_used_as_dut"] is False
    assert result["ubuntu_24h_counts_as_72h"] is False
    assert result["ubuntu_24h_specimen"]["classification"] == "SHORT"
    assert result["ubuntu_24h_specimen"]["wall_elapsed_s"] == 86400.001
    assert result["ubuntu_24h_specimen"]["below_259200"] is True
    assert result["ubuntu_24h_specimen"]["ubuntu_24h_counts_as_72h"] is False
    assert result["ubuntu_24h_specimen"]["ubuntu_24h_used_as_dut"] is False
    assert result["ubuntu_24h_specimen"]["clock_state"] == "NOT_STARTED"
    assert result["ubuntu_24h_specimen"]["l2_2_status"] == "NOT_STARTED"
    assert result["stall_hook_is_l2_2_acceptance"] is False
    _assert_gates_closed(result)
    after = {
        CHECKLIST: CHECKLIST.read_bytes(),
        START_DECISION: START_DECISION.read_bytes(),
        PREFLIGHT_JSON: PREFLIGHT_JSON.read_bytes(),
        STOP: STOP.read_bytes() if STOP.exists() else None,
    }
    assert after == before


@pytest.mark.parametrize(
    ("target", "key", "value", "needle"),
    [
        ("preflight", "l2_2_status", "PASS", "forged_pass"),
        ("preflight", "clock_state", "STARTED", "forged_clock_start"),
        ("preflight", "soak_launched", True, "soak_launched"),
        ("preflight", "production_7x24", "ACCEPTED", "forged_production_accepted"),
        ("preflight", "exit_0_is_gate_pass", True, "forged_pass"),
        ("preflight", "gate:can_start_clock", True, "forged_can_start_clock"),
        ("preflight", "gate:can_accept_l2_2", True, "forged_can_accept_l2_2"),
        ("preflight", "gate:can_close_l2_2", True, "forged_can_close_l2_2"),
        ("score", "l2_2_status", "PASS", "forged_pass"),
        ("score", "clock_state", "STARTED", "forged_clock_start"),
        ("score", "production_7x24", "ACCEPTED", "forged_production_accepted"),
        ("score", "gate:can_start_clock", True, "forged_can_start_clock"),
        ("score", "gate:can_accept_l2_2", True, "forged_can_accept_l2_2"),
        ("score", "gate:can_close_l2_2", True, "forged_can_close_l2_2"),
    ],
)
def test_forged_start_pass_accept_close_are_refused(target, key, value, needle):
    preflight_report, scored, r2_text = _honest()
    before = CHECKLIST.read_bytes()
    forged_pre = json.loads(json.dumps(preflight_report))
    forged_score = json.loads(json.dumps(scored))
    chosen = forged_pre if target == "preflight" else forged_score
    if key.startswith("gate:"):
        chosen["gates"][key.split(":", 1)[1]] = value
    else:
        chosen[key] = value
    result = _assess(forged_pre, forged_score, r2_text)
    assert result["ok"] is False
    assert needle in result["violations"]
    assert result["l2_2_status"] == "WITHHELD"
    assert result["clock_state"] == "WITHHELD"
    _assert_gates_closed(result)
    assert CHECKLIST.read_bytes() == before
    assert "**Not given**" in CHECKLIST.read_text(encoding="utf-8")


def test_forged_stall_hook_is_not_a_start_or_acceptance():
    preflight_report, scored, r2_text = _honest()
    forged = json.loads(json.dumps(preflight_report))
    forged["checks"]["stall_watchdog"]["implies_l2_2_acceptance"] = True
    forged["checks"]["stall_watchdog"]["implies_72h_pass"] = True
    forged["checks"]["stall_watchdog"]["binds_clock_start"] = True
    forged["checks"]["stall_watchdog"]["can_start_clock"] = True
    forged["checks"]["stall_watchdog"]["l2_2_status"] = "PASS"
    forged["checks"]["stall_watchdog"]["production_7x24"] = "ACCEPTED"
    forged["checks"]["stall_watchdog"]["clock_state"] = "STARTED"
    forged["checks"]["stall_watchdog"]["ubuntu_24h_used_as_dut"] = True
    result = _assess(forged, scored, r2_text)
    assert result["ok"] is False
    for needle in (
        "stall_implies_start",
        "forged_can_start_clock",
        "forged_pass",
        "forged_production_accepted",
        "forged_clock_start",
        "stall_ubuntu_dut",
    ):
        assert needle in result["violations"]
    assert result["l2_2_status"] == "WITHHELD"
    assert result["clock_state"] == "WITHHELD"
    assert result["stall_dut"] == "withheld"
    assert result["ubuntu_24h_used_as_dut"] is False
    assert result["stall_hook_is_l2_2_acceptance"] is False
    _assert_gates_closed(result)


def test_nested_pass_accepted_and_start_are_refused():
    preflight_report, scored, r2_text = _honest()
    forged = json.loads(json.dumps(preflight_report))
    forged["extra"] = {
        "l2_2_status": "PASS",
        "production_7x24": "ACCEPTED",
        "can_start_clock": True,
        "clock_state": "STARTED",
    }
    result = _assess(forged, scored, r2_text)
    assert result["ok"] is False
    for needle in (
        "forged_pass",
        "forged_production_accepted",
        "forged_can_start_clock",
        "forged_clock_start",
    ):
        assert needle in result["violations"]
    assert result["l2_2_status"] == "WITHHELD"
    _assert_gates_closed(result)


def test_scorer_exit_0_on_started_fixture_is_not_acceptance():
    preflight_report, _, r2_text = _honest()
    started = l2.score(l2.load_capture(WALL_SHORT))
    assert started["l2_2_status"] == "INCOMPLETE"
    assert started["clock_state"] != "NOT_STARTED"
    assert l2.validate_report(started) == []
    result = _assess(preflight_report, started, r2_text, score_exit=0)
    assert result["ok"] is False
    assert "forged_clock_start" in result["violations"]
    assert "l2_2_status" in result["violations"]
    assert result["l2_2_status"] == "WITHHELD"
    _assert_gates_closed(result)


def test_filled_checklist_text_is_refused_and_disk_stays_blank():
    preflight_report, scored, r2_text = _honest()
    before = CHECKLIST.read_bytes()
    filled = r2_text.replace("**Not given**", "**Ada 2026-02-01T00:00:00Z**", 1)
    result = _assess(preflight_report, scored, filled)
    assert result["ok"] is False
    assert result["r2_unfilled"] is False
    assert "r2_checklist_not_blank" in result["violations"]
    assert "r2_disagrees" in result["violations"]
    _assert_gates_closed(result)
    assert CHECKLIST.read_bytes() == before
    assert "The copy in git is unfilled." in CHECKLIST.read_text(encoding="utf-8")


def test_commands_score_the_not_started_fixture_and_do_not_launch_soak():
    commands = hc.l2_2_commands()
    assert len(commands) == 2
    assert commands[0][1].endswith("l2_2_preflight.py")
    assert commands[1][1].endswith("l2_2_score.py")
    assert commands[1][2] == "--capture"
    assert commands[1][3].endswith("tests/fixtures/l2_2/scaffold_clock_not_started.json")
    blob = " ".join(" ".join(cmd) for cmd in commands)
    assert "soak_2h" not in blob
    assert "schtasks" not in blob
    pytest_cmd = hc.pytest_command()
    assert pytest_cmd[1:4] == ["-m", "pytest", "tests/"]
    assert pytest_cmd[4] == "-q"
    assert "soak_2h" not in " ".join(pytest_cmd)


def test_source_keeps_existing_steps_and_does_not_register_tasks():
    text = (ROOT / "scripts" / "health_check.py").read_text(encoding="utf-8")
    main = text.split("def main", 1)[1]
    order = [
        '"emergency_stop"',
        '"import_control_plane"',
        '"l1_dry_protocol"',
        '"seed_one"',
        '"l1_auto_loop_once"',
        "l2_2_offline_step()",
        "run_pytest_step()",
    ]
    indexes = [main.index(token) for token in order]
    assert indexes == sorted(indexes)
    assert 'step(\n        "l2_2_offline"' in text
    assert 'step("pytest_suite"' in text
    assert "soak_2h.main" not in text
    assert "schtasks" not in text
    assert "Register-ScheduledTask" not in text
    assert "Enable-ScheduledTask" not in text


def test_interpreter_prefers_the_running_executable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hc.sys, "executable", sys.executable)
    assert hc.interpreter() == sys.executable


def test_interpreter_falls_back_to_python3(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hc.sys, "executable", "")

    def which(name: str) -> str | None:
        return "/usr/bin/python3" if name == "python3" else None

    monkeypatch.setattr(hc.shutil, "which", which)
    assert hc.interpreter() == "/usr/bin/python3"


def test_pytest_step_is_not_acceptance(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("HEALTH_CHECK_SKIP_PYTEST", raising=False)
    seen: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        seen["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="12 passed in 0.01s\n", stderr="")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    row = hc.run_pytest_step()
    assert seen["cmd"][1:5] == ["-m", "pytest", "tests/", "-q"]
    assert "soak_2h" not in " ".join(seen["cmd"])
    assert row["ok"] is True
    assert row["step"] == "pytest_suite"
    assert row["is_l2_2_acceptance"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["soak_launched"] is False
    assert row["exit_0_is_gate_pass"] is False
    assert "unit_suite_not_l2_2_acceptance" in row["detail"]


def test_pytest_failure_does_not_open_gates(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("HEALTH_CHECK_SKIP_PYTEST", raising=False)

    def fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="1 failed\n", stderr="")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    row = hc.run_pytest_step()
    assert row["ok"] is False
    assert row["is_l2_2_acceptance"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False


def test_pytest_step_skips_reentry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_health_check.py::test (call)")

    def fake_run(*_args, **_kwargs):
        raise AssertionError("pytest must not re-enter from inside pytest")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    row = hc.run_pytest_step()
    assert row["ok"] is True
    assert row["is_l2_2_acceptance"] is False
    assert "not_an_acceptance" in row["detail"]


def test_summary_never_grants_gates():
    healthy = {
        "step": "l2_2_offline",
        "ok": True,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "r2_unfilled": True,
        "can_start_clock": False,
    }
    summary = hc.summarize([healthy], True)
    assert summary["overall_ok"] is True
    assert summary["l2_2_status"] == "NOT_STARTED"
    assert summary["clock_state"] == "NOT_STARTED"
    assert summary["l2_2_checked"] is True
    assert summary["r2_unfilled"] is True
    assert summary["start_decision_unfilled"] is None
    assert summary["soak_launched"] is False
    assert summary["production_7x24"] == "NOT_ACCEPTED"
    assert summary["can_start_clock"] is False
    assert summary["can_accept_l2_2"] is False
    assert summary["can_close_l2_2"] is False
    assert summary["gate_result"] == "NOT_A_GATE"
    assert summary["exit_0_is_gate_pass"] is False
    assert summary["pytest_is_l2_2_acceptance"] is False
    assert summary["stall_dut"] == "withheld"
    assert summary["ubuntu_24h_used_as_dut"] is False
    assert summary["ubuntu_24h_counts_as_72h"] is False
    assert summary["ubuntu_24h_specimen"]["classification"] == "withheld"
    assert summary["ubuntu_24h_specimen"]["ubuntu_24h_used_as_dut"] is False
    assert summary["ubuntu_24h_specimen"]["clock_state"] == "NOT_STARTED"
    assert summary["stall_hook_is_l2_2_acceptance"] is False

    forged = {
        "step": "l2_2_offline",
        "ok": False,
        "l2_2_status": "WITHHELD",
        "clock_state": "WITHHELD",
        "r2_unfilled": True,
        "can_start_clock": True,
        "can_accept_l2_2": True,
        "can_close_l2_2": True,
    }
    refused = hc.summarize([forged], False)
    assert refused["overall_ok"] is False
    assert refused["l2_2_status"] == "WITHHELD"
    assert refused["can_start_clock"] is False
    assert refused["can_accept_l2_2"] is False
    assert refused["can_close_l2_2"] is False
    assert refused["soak_launched"] is False
    assert refused["production_7x24"] == "NOT_ACCEPTED"
    assert refused["ubuntu_24h_counts_as_72h"] is False
    assert refused["ubuntu_24h_specimen"]["classification"] == "withheld"


def test_ubuntu_specimen_stays_short_while_the_clock_stays_not_started():
    preflight_report, scored, r2_text = _honest()
    specimen = preflight_report["ubuntu_24h_specimen"]
    assert specimen["classification"] == "SHORT"
    assert specimen["wall_elapsed_s"] == 86400.001
    assert specimen["below_259200"] is True
    assert specimen["ubuntu_24h_counts_as_72h"] is False
    assert specimen["ubuntu_24h_used_as_dut"] is False
    assert specimen["l2_2_status"] == "NOT_STARTED"
    assert specimen["clock_state"] == "NOT_STARTED"
    blob = json.dumps(preflight_report)
    assert '"clock_state": "SHORT"' not in blob
    assert '"l2_2_status": "INCOMPLETE"' not in blob
    result = _assess(preflight_report, scored, r2_text)
    assert result["ok"] is True, result["violations"]
    assert result["l2_2_status"] == "NOT_STARTED"
    assert result["clock_state"] == "NOT_STARTED"
    assert result["ubuntu_24h_counts_as_72h"] is False
    assert result["historical_shorts_are_additive"] is False
    assert result["sum_of_shorts_counts_toward_gate"] is False
    viewed = result["ubuntu_24h_specimen"]
    assert viewed["classification"] == "SHORT"
    assert viewed["wall_elapsed_s"] == 86400.001
    assert viewed["below_259200"] is True
    assert viewed["ubuntu_24h_counts_as_72h"] is False
    assert viewed["ubuntu_24h_used_as_dut"] is False
    assert viewed["is_stall_dut"] is False
    assert viewed["clock_state"] == "NOT_STARTED"
    assert viewed["l2_2_status"] == "NOT_STARTED"
    _assert_gates_closed(result)


def test_forged_ubuntu_specimen_cannot_count_as_72h_start_or_dut():
    preflight_report, scored, r2_text = _honest()
    forged = json.loads(json.dumps(preflight_report))
    for target in (forged["ubuntu_24h_specimen"], forged["checks"]["ubuntu_24h_specimen"]):
        target["classification"] = "72h"
        target["ubuntu_24h_counts_as_72h"] = True
        target["counts_toward_72h_gate"] = True
        target["ubuntu_24h_used_as_dut"] = True
        target["is_stall_dut"] = True
        target["is_l2_2_acceptance"] = True
        target["binds_clock_start"] = True
        target["wrapped_as_started_capture"] = True
        target["can_start_clock"] = True
        target["l2_2_status"] = "PASS"
        target["clock_state"] = "STARTED"
        target["production_7x24"] = "ACCEPTED"
        target["wall_elapsed_s"] = 259200
        target["below_259200"] = False
    result = _assess(forged, scored, r2_text)
    assert result["ok"] is False
    for needle in (
        "ubuntu_24h_as_72h",
        "ubuntu_24h_as_dut",
        "ubuntu_24h_as_acceptance",
        "ubuntu_24h_as_start",
        "forged_can_start_clock",
        "forged_pass",
        "forged_clock_start",
        "forged_production_accepted",
    ):
        assert needle in result["violations"]
    assert result["l2_2_status"] == "WITHHELD"
    assert result["clock_state"] == "WITHHELD"
    assert result["ubuntu_24h_used_as_dut"] is False
    assert result["ubuntu_24h_counts_as_72h"] is False
    viewed = result["ubuntu_24h_specimen"]
    assert viewed["classification"] == "withheld"
    assert viewed["ubuntu_24h_counts_as_72h"] is False
    assert viewed["ubuntu_24h_used_as_dut"] is False
    assert viewed["clock_state"] == "NOT_STARTED"
    assert viewed["l2_2_status"] == "NOT_STARTED"
    _assert_gates_closed(result)


def test_summary_drops_a_forged_specimen_claim():
    forged = {
        "step": "l2_2_offline",
        "ok": True,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "ubuntu_24h_specimen": {
            "ok": True,
            "classification": "PASS",
            "ubuntu_24h_counts_as_72h": True,
            "ubuntu_24h_used_as_dut": True,
            "can_start_clock": True,
            "l2_2_status": "PASS",
            "clock_state": "STARTED",
            "production_7x24": "ACCEPTED",
        },
        "can_start_clock": True,
    }
    summary = hc.summarize([forged], True)
    assert summary["l2_2_status"] == "NOT_STARTED"
    assert summary["clock_state"] == "NOT_STARTED"
    assert summary["can_start_clock"] is False
    assert summary["can_accept_l2_2"] is False
    assert summary["can_close_l2_2"] is False
    assert summary["ubuntu_24h_counts_as_72h"] is False
    assert summary["ubuntu_24h_used_as_dut"] is False
    assert summary["ubuntu_24h_specimen"]["classification"] == "withheld"
    assert summary["ubuntu_24h_specimen"]["clock_state"] == "NOT_STARTED"
    assert summary["production_7x24"] == "NOT_ACCEPTED"
    assert summary["historical_shorts_are_additive"] is False
    assert summary["sum_of_shorts_counts_toward_gate"] is False


def test_honest_preflight_keeps_shorts_non_additive():
    preflight_report, scored, r2_text = _honest()
    row = preflight_report["non_additivity"]
    assert row["ok"] is True
    assert row["historical_shorts_are_additive"] is False
    assert row["sum_of_shorts_counts_toward_gate"] is False
    assert row["d1_windows_metrics_file"] is None
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    three = next(item for item in row["refused_sums"] if item["label"] == "three_times_86400")
    assert three["sum_seconds"] == 259200.0
    assert three["naive_sum_reaches_259200"] is True
    assert three["counts_toward_gate"] is False
    paired = next(item for item in row["refused_sums"] if item["label"] == "ubuntu_24h_plus_another_86400")
    assert paired["sum_seconds"] == 172800.001
    assert paired["counts_toward_gate"] is False
    assert scored["non_additivity"]["additive_claim"] is False
    assert scored["non_additivity"]["historical_shorts_are_additive"] is False
    result = _assess(preflight_report, scored, r2_text)
    assert result["ok"] is True, result["violations"]
    assert result["violations"] == []
    assert result["l2_2_status"] == "NOT_STARTED"
    assert result["clock_state"] == "NOT_STARTED"
    assert result["historical_shorts_are_additive"] is False
    assert result["sum_of_shorts_counts_toward_gate"] is False
    assert result["production_7x24"] == "NOT_ACCEPTED"
    _assert_gates_closed(result)


def test_forged_additive_report_fails_closed_without_opening_gates():
    preflight_report, scored, r2_text = _honest()
    forged = json.loads(json.dumps(preflight_report))
    forged["non_additivity"]["historical_shorts_are_additive"] = True
    forged["non_additivity"]["sum_of_shorts_counts_toward_gate"] = True
    forged["non_additivity"]["l2_2_status"] = "PASS"
    forged["non_additivity"]["clock_state"] = "STARTED"
    forged["non_additivity"]["can_start_clock"] = True
    forged["non_additivity"]["production_7x24"] = "ACCEPTED"
    forged["checks"]["non_additivity"] = json.loads(json.dumps(forged["non_additivity"]))
    for item in forged["non_additivity"]["refused_sums"]:
        if item["naive_sum_reaches_259200"] is True:
            item["counts_toward_gate"] = True
    for item in forged["checks"]["non_additivity"]["refused_sums"]:
        if item["naive_sum_reaches_259200"] is True:
            item["counts_toward_gate"] = True
    forged_score = json.loads(json.dumps(scored))
    forged_score["non_additivity"]["historical_shorts_are_additive"] = True
    forged_score["non_additivity"]["sum_of_shorts_counts_toward_gate"] = True
    forged_score["non_additivity"]["counts_toward_gate"] = True
    forged_score["non_additivity"]["additive_claim"] = True
    forged_score["l2_2_status"] = "PASS"
    forged_score["clock_state"] = "WALL_OBSERVED"
    forged_score["production_7x24"] = "ACCEPTED"
    result = _assess(forged, forged_score, r2_text)
    assert result["ok"] is False
    for needle in (
        "additive_historical_shorts",
        "non_additivity",
        "forged_pass",
        "forged_clock_start",
        "forged_can_start_clock",
        "forged_production_accepted",
    ):
        assert needle in result["violations"]
    assert result["l2_2_status"] == "WITHHELD"
    assert result["clock_state"] == "WITHHELD"
    assert result["historical_shorts_are_additive"] is False
    assert result["sum_of_shorts_counts_toward_gate"] is False
    assert result["ubuntu_24h_counts_as_72h"] is False
    _assert_gates_closed(result)


def test_summary_drops_a_forged_additive_claim():
    forged = {
        "step": "l2_2_offline",
        "ok": True,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "historical_shorts_are_additive": True,
        "sum_of_shorts_counts_toward_gate": True,
        "can_start_clock": True,
        "production_7x24": "ACCEPTED",
    }
    summary = hc.summarize([forged], True)
    assert summary["l2_2_status"] == "NOT_STARTED"
    assert summary["clock_state"] == "NOT_STARTED"
    assert summary["can_start_clock"] is False
    assert summary["can_accept_l2_2"] is False
    assert summary["can_close_l2_2"] is False
    assert summary["historical_shorts_are_additive"] is False
    assert summary["sum_of_shorts_counts_toward_gate"] is False
    assert summary["production_7x24"] == "NOT_ACCEPTED"
    assert summary["soak_launched"] is False


def test_docs_call_health_check_a_not_started_check():
    readme = (ROOT / "docs" / "progress" / "l2_2" / "README.md").read_text(encoding="utf-8")
    package = (ROOT / "docs" / "progress" / "EVIDENCE_PACKAGE.md").read_text(encoding="utf-8")
    section = package.split("## L2-2", 1)[1].split("\n## ", 1)[0]
    decision = START_DECISION.read_text(encoding="utf-8")
    assert "scripts/health_check.py" in readme
    assert "not a start decision" in readme
    assert "START_DECISION.md" in readme
    assert "scripts/health_check.py" in section
    assert "START_DECISION.md" in section
    assert "NOT STARTED" in section
    assert "NOT ACCEPTED" in section
    assert "The copy in git is unfilled." in CHECKLIST.read_text(encoding="utf-8")
    assert "The copy in git is unfilled." in decision
    assert "**Not given**" in decision
    assert "Filling this file alone does not start the soak" in decision


@pytest.mark.parametrize(
    "snippet",
    [
        "clock_state: STARTED",
        "l2_2_status: PASS",
        "production_7x24: ACCEPTED",
        "can_start_clock: true",
    ],
)
def test_forged_start_decision_text_keeps_gates_false(snippet: str):
    preflight_report, scored, r2_text = _honest()
    before = START_DECISION.read_bytes()
    forged = before.decode("utf-8") + "\n" + snippet + "\n"
    result = _assess(preflight_report, scored, r2_text, start_decision_text=forged)
    assert result["ok"] is False
    assert "start_decision_forged" in result["violations"]
    assert "start_decision_not_blank" in result["violations"]
    assert result["start_decision_unfilled"] is False
    assert result["l2_2_status"] == "WITHHELD"
    assert result["clock_state"] == "WITHHELD"
    _assert_gates_closed(result)
    assert START_DECISION.read_bytes() == before


def test_preflight_of_forged_start_decision_does_not_open_gates(tmp_path: Path):
    original = START_DECISION.read_text(encoding="utf-8")
    forged_path = tmp_path / "START_DECISION.md"
    forged_path.write_text(original + "\ncan_start_clock: true\n", encoding="utf-8")
    forged_report = pre.preflight(start_decision_path=forged_path)
    _, scored, r2_text = _honest()
    assert forged_report["l2_2_status"] == "NOT_STARTED"
    assert forged_report["gates"]["can_start_clock"] is False
    assert forged_report["not_started_scaffold_intact"] is False
    result = _assess(
        forged_report,
        scored,
        r2_text,
        start_decision_text=forged_path.read_text(encoding="utf-8"),
        preflight_exit=2,
    )
    assert result["ok"] is False
    assert "start_decision_forged" in result["violations"]
    assert "scaffold_not_intact" in result["violations"]
    assert "preflight_exit" in result["violations"]
    _assert_gates_closed(result)
    assert START_DECISION.read_text(encoding="utf-8") == original
