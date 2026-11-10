"""L2-2 72h scorer. Fixtures are synthetic and dated 2026-02-01.

They are not a host soak, not Ubuntu-24H, and not the 2026-11-03..06 incident.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import l2_2_score as l2  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "l2_2"
SCHEMA_DOC = ROOT / "docs" / "progress" / "l2_2" / "SCHEMA.json"
def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fixture_timestamps(doc: object) -> list[str]:
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith("2026-"):
            found.append(node)

    walk(doc)
    return found


def test_schema_ids_match_contract():
    doc = json.loads(SCHEMA_DOC.read_text(encoding="utf-8"))
    assert doc["capture_schema"] == l2.SCHEMA_CAPTURE
    assert doc["report_schema"] == l2.SCHEMA_REPORT
    assert doc["wall_required_seconds"] == l2.WALL_REQUIRED_SECONDS == 259200
    assert doc["production_7x24"] == "NOT_ACCEPTED"
    assert doc["can_accept_l2_2"] is False
    assert doc["can_close_l2_2"] is False
    assert doc["can_start_clock"] is False
    assert doc["product_l2_task_split"] == "NOT_STARTED"
    assert doc["interactive_registration"] == "founder_gated_out_of_scope"
    assert "PASS" not in doc["l2_2_status_emitted"]


def test_scaffold_fixtures_stay_away_from_the_incident_window():
    for path in FIXTURES.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["evidence_class"] == "scaffold"
        assert doc["synthetic"] is True
        stamps = _fixture_timestamps(doc)
        assert stamps, path.name
        for stamp in stamps:
            assert stamp.startswith("2026-02-"), stamp


def test_clock_not_started_is_the_canonical_report():
    report = l2.score(_load("scaffold_clock_not_started.json"))
    assert report["label"] == "scaffold"
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["verified"] is False
    assert report["supervision_verified"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["business_verdict"] == "UNSCORED"
    assert report["business_fail"] is False
    assert report["product_l2_task_split"] == "NOT_STARTED"
    assert report["interactive_registration"] == "founder_gated_out_of_scope"
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_close_l2_2"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["bars_all_true"] is False
    assert report["wall"]["counts_toward_gate"] is False
    assert report["wall"]["elapsed_meets_259200"] is False
    assert report["gates"]["blockers"] == [
        "tool_does_not_accept_l2_2",
        "tool_does_not_start_clock",
        "production_7x24_not_accepted",
        "interactive_registration_founder_gated_out_of_scope",
        "observation_track_has_not_accepted",
        "scaffold_fixture_not_host_evidence",
        "clock_not_started",
    ]
    assert report["l2_4"]["status"] == "INCOMPLETE"
    assert report["l2_4"]["relitigated"] is False
    assert report["l2_4"]["tip"] == l2.L2_4_CROSSLINK["tip"]
    assert report["triage"] == {
        "business": False,
        "host": False,
        "supervision": False,
        "policy": False,
    }
    assert l2.validate_report(report) == []
    assert "Not a host 72h soak" in report["source"]["note"]


def test_next_steps_do_not_ask_to_enable_interactive_duty():
    report = l2.score(_load("scaffold_clock_not_started.json"))
    assert report["next_steps"] == list(l2.NEXT_STEPS)
    joined = "\n".join(report["next_steps"])
    assert "Do not register, create, or enable" in joined
    assert "founder major gate" in joined
    assert "NOT STARTED" in joined
    assert "max-wall-seconds 259200" in joined
    for step in report["next_steps"]:
        lowered = step.lower()
        assert "schtasks" not in lowered
        assert "register-scheduledtask" not in lowered
        assert not lowered.startswith("enable")
        assert not lowered.startswith("register")
    assert report["definition"]["interactive_schtasks"] == "out_of_scope"
    assert report["definition"]["exit0_is_business"] is False


def test_short_wall_is_not_a_72h():
    report = l2.score(_load("scaffold_wall_short.json"))
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["clock_state"] == "SHORT"
    assert report["wall"]["elapsed_seconds"] == 86400.001
    assert report["wall"]["elapsed_meets_259200"] is False
    assert report["wall"]["counts_toward_gate"] is False
    assert report["bars"]["with_work"] is True
    assert report["bars"]["wall_monotonic_72h"] is False
    blockers = report["gates"]["blockers"]
    assert "wall_short" in blockers
    assert "max_wall_seconds_not_72h" in blockers
    assert "exit0_is_not_business" not in blockers
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"


def test_exit0_alone_is_not_business_progress():
    report = l2.score(_load("scaffold_exit0_only.json"))
    assert report["wall"]["counts_toward_gate"] is True
    assert report["bars"]["with_work"] is False
    assert report["business_fail"] is False
    assert report["business_verdict"] == "UNSCORED"
    assert "exit0_is_not_business" in report["gates"]["blockers"]
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["gates"]["can_accept_l2_2"] is False


def test_full_scaffold_wall_still_cannot_accept():
    report = l2.score(_load("scaffold_full_wall_cannot_accept.json"))
    assert report["clock_state"] == "WALL_OBSERVED"
    assert report["wall"]["counts_toward_gate"] is True
    assert report["bars"]["with_work"] is True
    assert report["bars"]["summary_reconciled"] is True
    assert report["bars"]["r2_declared_before_start"] is True
    assert report["bars"]["r3_receipt_present"] is True
    assert report["bars"]["host_evidence"] is False
    assert report["bars_all_true"] is False
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["supervision_verified"] is False
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_close_l2_2"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert "scaffold_fixture_not_host_evidence" in report["gates"]["blockers"]


def test_host_shaped_full_wall_still_cannot_accept():
    doc = _load("scaffold_full_wall_cannot_accept.json")
    doc["evidence_class"] = "host_observation"
    doc["synthetic"] = False
    doc["host"] = "fixture-host"
    doc["git_sha"] = "fixture-not-a-commit"
    doc["note"] = "In-memory host-shaped bundle dated 2026-02-01. Not observation-track acceptance."
    report = l2.score(doc)
    assert report["label"] == "host_observation_unverified"
    assert report["bars_all_true"] is True
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["verified"] is False
    assert report["supervision_verified"] is False
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["product_l2_task_split"] == "NOT_STARTED"
    for permanent in l2.PERMANENT_BLOCKERS:
        assert permanent in report["gates"]["blockers"]
    assert "scaffold_fixture_not_host_evidence" not in report["gates"]["blockers"]
    assert l2.validate_report(report) == []


def test_interactive_registration_does_not_count_or_start():
    report = l2.score(_load("scaffold_interactive_forbidden.json"))
    assert report["runner"]["rejected"] is True
    assert report["runner"]["allowed"] is False
    assert report["wall"]["elapsed_meets_259200"] is True
    assert report["wall"]["counts_toward_gate"] is False
    assert report["triage"]["policy"] is True
    assert report["triage"]["business"] is False
    assert report["triage"]["supervision"] is False
    assert "interactive_registration_forbidden" in report["gates"]["blockers"]
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["interactive_registration"] == "founder_gated_out_of_scope"
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_start_clock"] is False


def test_registration_without_a_clock_stays_not_started():
    doc = _load("scaffold_clock_not_started.json")
    doc["runner"] = {
        "kind": "logon_schtasks",
        "interactive": True,
        "registered_this_run": True,
        "task_names": ["AIStudioOS-Grok-L1"],
    }
    report = l2.score(doc)
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["triage"]["policy"] is True
    assert "interactive_registration_forbidden" in report["gates"]["blockers"]
    assert "clock_not_started" in report["gates"]["blockers"]
    assert report["gates"]["can_start_clock"] is False


def test_ended_experiment_watch_is_supervision_not_business_fail():
    doc = _load("scaffold_wall_short.json")
    doc["supervision"]["watch_target"] = "ended_experiment"
    report = l2.score(doc)
    assert report["triage"]["supervision"] is True
    assert report["triage"]["business"] is False
    assert report["business_fail"] is False
    assert "ended_experiment_watch_forbidden" in report["gates"]["blockers"]
    assert report["l2_2_status"] == "INCOMPLETE"


def test_yellow_gap_is_not_a_fail_and_red_gap_is_supervision():
    doc = _load("scaffold_full_wall_cannot_accept.json")
    doc["supervision"]["coverage_gaps"] = [
        {"utc": "2026-02-01T01:00:00Z", "seconds": 30},
        {"utc": "2026-02-01T02:00:00Z", "seconds": 300},
    ]
    yellow = l2.score(doc)
    assert yellow["coverage_gaps"]["yellow"] == 2
    assert yellow["coverage_gaps"]["red"] == 0
    assert yellow["triage"]["supervision"] is False
    assert yellow["triage"]["business"] is False
    assert "red_coverage_gap" not in yellow["gates"]["blockers"]

    doc["supervision"]["coverage_gaps"].append(
        {"utc": "2026-02-01T03:00:00Z", "seconds": 301}
    )
    red = l2.score(doc)
    assert red["coverage_gaps"]["red"] == 1
    assert red["triage"]["supervision"] is True
    assert red["triage"]["business"] is False
    assert red["business_fail"] is False
    assert "red_coverage_gap" in red["gates"]["blockers"]
    assert red["gates"]["can_accept_l2_2"] is False


def test_cycles_times_interval_is_not_a_monotonic_wall():
    doc = _load("scaffold_full_wall_cannot_accept.json")
    doc["wall"]["source"] = "cycles_times_interval"
    report = l2.score(doc)
    assert report["clock_state"] == "INCOMPLETE"
    assert report["wall"]["elapsed_meets_259200"] is True
    assert report["wall"]["counts_toward_gate"] is False
    assert "wall_not_monotonic" in report["gates"]["blockers"]
    assert report["l2_2_status"] == "INCOMPLETE"


def test_summary_mismatch_blocks_reconciliation():
    doc = _load("scaffold_full_wall_cannot_accept.json")
    doc["metrics"]["cycles_with_work"] = 2
    report = l2.score(doc)
    assert report["reconciliation"]["status"] == "mismatch"
    assert "cycles_with_work" in report["reconciliation"]["mismatches"]
    assert "metrics_summary_mismatch" in report["gates"]["blockers"]
    assert report["bars"]["summary_reconciled"] is False
    assert report["gates"]["can_accept_l2_2"] is False


def test_forged_claim_in_the_capture_is_ignored():
    doc = _load("scaffold_clock_not_started.json")
    doc["claimed_l2_2_status"] = "PASS"
    doc["claimed_production_7x24"] = "ACCEPTED"
    report = l2.score(doc)
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["gates"]["can_accept_l2_2"] is False
    assert "forged_claim_ignored" in report["gates"]["blockers"]


def test_forged_pass_report_is_rejected():
    forged = {
        "schema": l2.SCHEMA_REPORT,
        "evidence_class": "host_observation",
        "label": "host_observation_unverified",
        "production_7x24": "ACCEPTED",
        "l2_2_status": "PASS",
        "verified": True,
        "supervision_verified": True,
        "business_fail": True,
        "business_verdict": "PASS",
        "product_l2_task_split": "DONE",
        "interactive_registration": "approved",
        "gates": {
            "can_accept_l2_2": True,
            "can_close_l2_2": True,
            "can_start_clock": True,
        },
        "l2_4": {"status": "PASS", "relitigated": True},
        "next_steps": [],
    }
    violations = set(l2.validate_report(forged))
    assert "forged_pass" in violations
    assert "production_claim" in violations
    assert "forged_accept" in violations
    assert "forged_close" in violations
    assert "forged_clock_start" in violations
    assert "verified_claim" in violations
    assert "supervision_verified_claim" in violations
    assert "business_fail_not_supported" in violations
    assert "product_l2_claim" in violations
    assert "interactive_registration" in violations
    assert "l2_4_crosslink" in violations


def test_ubuntu_24h_metrics_cannot_be_relabelled_as_72h():
    metrics = json.loads(
        (ROOT / "docs" / "progress" / "soak_2h" / "metrics.json").read_text(encoding="utf-8")
    )
    assert metrics["wall_elapsed_s"] == 86400.001
    assert metrics["max_wall_seconds"] == 86400
    doc = _load("scaffold_wall_short.json")
    doc["evidence_class"] = "host_observation"
    doc["synthetic"] = False
    doc["host"] = metrics["host"]
    doc["git_sha"] = metrics["sha_full"]
    doc["note"] = "In-memory reuse of Ubuntu-24H metrics.json. Not a 72h observation package."
    doc["captured_utc"] = metrics["utc_end"]
    doc["clock"] = {
        "started": True,
        "start_utc": "2026-11-06T00:00:01Z",
        "end_utc": metrics["utc_end"],
    }
    doc["wall"] = {
        "required_seconds": 259200,
        "elapsed_seconds": metrics["wall_elapsed_s"],
        "max_wall_seconds": metrics["max_wall_seconds"],
        "source": "monotonic",
    }
    doc["metrics"] = {
        "final": metrics["final"],
        "stopped_early": metrics["stopped_early"],
        "cycles_ran": metrics["cycles_ran"],
        "cycles_exit0": metrics["cycles_exit0"],
        "cycles_with_work": metrics["cycles_with_work"],
        "cycles_idle": metrics["cycles_idle"],
        "wall_elapsed_s": metrics["wall_elapsed_s"],
        "max_wall_seconds": metrics["max_wall_seconds"],
        "via_l1": metrics["via_l1"],
    }
    doc["summary_rows"] = []
    report = l2.score(doc)
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["clock_state"] == "SHORT"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["wall"]["counts_toward_gate"] is False
    assert "wall_short" in report["gates"]["blockers"]
    assert "summary_rows_missing" in report["gates"]["blockers"]
    assert report["business_fail"] is False


def test_rejects_shortened_gate_naive_time_and_incident_scaffold():
    shortened = _load("scaffold_clock_not_started.json")
    shortened["wall"]["required_seconds"] = 86400
    with pytest.raises(l2.CaptureError, match="259200"):
        l2.score(shortened)

    with pytest.raises(l2.CaptureError, match="naive"):
        l2.score(_load("scaffold_naive_timestamp.json"))

    incident = _load("scaffold_clock_not_started.json")
    incident["captured_utc"] = "2026-11-04T00:00:00Z"
    with pytest.raises(l2.CaptureError, match="2026-11-03"):
        l2.score(incident)

    mislabeled = _load("scaffold_clock_not_started.json")
    mislabeled["evidence_class"] = "host_observation"
    with pytest.raises(l2.CaptureError, match="synthetic"):
        l2.score(mislabeled)


def test_cli_scaffold_exit_0_and_invalid_exit_2(tmp_path: Path):
    script = ROOT / "scripts" / "l2_2_score.py"
    out = tmp_path / "report.json"
    ok = subprocess.run(
        [
            sys.executable,
            str(script),
            "--capture",
            str(FIXTURES / "scaffold_clock_not_started.json"),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["gates"]["can_accept_l2_2"] is False
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


def test_scorer_does_not_launch_a_runner_or_register_tasks():
    text = (ROOT / "scripts" / "l2_2_score.py").read_text(encoding="utf-8")
    for token in (
        "subprocess",
        "os.system",
        "Popen",
        "Register-ScheduledTask",
        "Enable-ScheduledTask",
        "Start-ScheduledTask",
        "schtasks ",
        "schtasks.exe",
    ):
        assert token not in text
    assert "interactive_schtasks" in text
    assert "soak_2h.py" in text


def test_committed_scaffold_report_matches_the_scorer():
    path = ROOT / "docs" / "progress" / "l2_2" / "scaffold" / "report.json"
    committed = json.loads(path.read_text(encoding="utf-8"))
    fresh = l2.score(_load("scaffold_clock_not_started.json"))
    assert committed == fresh
    assert committed["l2_2_status"] == "NOT_STARTED"
    assert committed["label"] == "scaffold"
    assert committed["source"]["collector_mode"] == "offline_score"


def test_gap_boundary_helpers():
    assert l2._classify_gap(12.9) == "ok"
    assert l2._classify_gap(13) == "yellow"
    assert l2._classify_gap(300) == "yellow"
    assert l2._classify_gap(300.1) == "red"
    assert l2.INCIDENT_START == datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert l2.INCIDENT_END == datetime(2026, 11, 6, tzinfo=timezone.utc)


def test_historical_short_walls_are_not_additive_toward_259200():
    cases = (
        ([86400.001], 86400.001, False),
        ([86400.001, 86400], 172800.001, False),
        ([86400, 86400, 86400], 259200.0, True),
        ([86400.001, 86400, 86400], 259200.001, True),
    )
    for components, total, naive in cases:
        assessed = l2.assess_short_sum(components)
        assert assessed["sum_seconds"] == total
        assert assessed["naive_sum_reaches_259200"] is naive
        assert assessed["counts_toward_gate"] is False
        assert assessed["historical_shorts_are_additive"] is False
        assert assessed["continuous_monotonic_wall"] is False
        assert assessed["single_live_soak"] is False
        assert assessed["wall_required_seconds"] == 259200
    standing = l2.standing_non_additivity(None)
    assert standing["historical_shorts_are_additive"] is False
    assert standing["sum_of_shorts_counts_toward_gate"] is False
    assert standing["additive_claim"] is False
    assert standing["counts_toward_gate"] is False
    report = l2.score(_load("scaffold_clock_not_started.json"))
    assert report["non_additivity"] == standing
    assert report["wall"]["additive_claim"] is False
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["gates"]["can_start_clock"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"


def _additive_capture(components: list[float], elapsed: float, source: str = "monotonic") -> dict:
    doc = _load("scaffold_full_wall_cannot_accept.json")
    doc["note"] = "In-memory sum of ended SHORT walls. Not one continuous 72h soak."
    doc["wall"]["elapsed_seconds"] = elapsed
    doc["wall"]["source"] = source
    doc["wall"]["components"] = components
    doc["wall"]["additive"] = True
    doc["metrics"]["wall_elapsed_s"] = elapsed
    return doc


def test_forged_additive_sum_does_not_count_as_72h():
    summed = _additive_capture([86400.001, 86400], 172800.001)
    report = l2.score(summed)
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["clock_state"] == "INCOMPLETE"
    assert report["wall"]["counts_toward_gate"] is False
    assert report["wall"]["elapsed_meets_259200"] is False
    assert report["wall"]["additive_claim"] is True
    assert report["non_additivity"]["historical_shorts_are_additive"] is False
    assert report["non_additivity"]["sum_of_shorts_counts_toward_gate"] is False
    assert report["non_additivity"]["claimed_sum_seconds"] == 172800.001
    assert report["non_additivity"]["naive_sum_reaches_259200"] is False
    assert report["non_additivity"]["counts_toward_gate"] is False
    assert "additive_historical_shorts" in report["gates"]["blockers"]
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_start_clock"] is False
    assert report["gates"]["can_close_l2_2"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert l2.validate_report(report) == []

    three = _additive_capture([86400, 86400, 86400], 259200.0, source="sum")
    three["claimed_l2_2_status"] = "PASS"
    three["claimed_production_7x24"] = "ACCEPTED"
    report = l2.score(three)
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["clock_state"] == "INCOMPLETE"
    assert report["wall"]["counts_toward_gate"] is False
    assert report["wall"]["elapsed_meets_259200"] is False
    assert report["bars"]["wall_monotonic_72h"] is False
    assert report["non_additivity"]["naive_sum_reaches_259200"] is True
    assert report["non_additivity"]["claimed_sum_seconds"] == 259200.0
    assert report["non_additivity"]["counts_toward_gate"] is False
    assert report["non_additivity"]["historical_shorts_are_additive"] is False
    assert "additive_historical_shorts" in report["gates"]["blockers"]
    assert "forged_claim_ignored" in report["gates"]["blockers"]
    assert "wall_not_monotonic" in report["gates"]["blockers"]
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_start_clock"] is False
    assert l2.validate_report(report) == []

    times = _additive_capture([], 259200.0)
    times["wall"].pop("components")
    times["wall"]["times_24h"] = 3
    report = l2.score(times)
    assert report["non_additivity"]["claimed_component_count"] == 3
    assert report["non_additivity"]["claimed_sum_seconds"] == 259200.0
    assert report["non_additivity"]["naive_sum_reaches_259200"] is True
    assert report["wall"]["counts_toward_gate"] is False
    assert report["clock_state"] == "INCOMPLETE"
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["production_7x24"] == "NOT_ACCEPTED"


def test_forged_additive_report_fails_closed():
    honest = l2.score(_load("scaffold_clock_not_started.json"))
    forged = json.loads(json.dumps(honest))
    forged["non_additivity"]["historical_shorts_are_additive"] = True
    forged["non_additivity"]["sum_of_shorts_counts_toward_gate"] = True
    forged["non_additivity"]["counts_toward_gate"] = True
    forged["non_additivity"]["additive_claim"] = True
    forged["wall"]["components"] = [86400, 86400, 86400]
    forged["wall"]["counts_toward_gate"] = True
    forged["wall"]["source"] = "sum"
    forged["wall"]["elapsed_seconds"] = 259200
    forged["l2_2_status"] = "PASS"
    forged["clock_state"] = "WALL_OBSERVED"
    forged["production_7x24"] = "ACCEPTED"
    forged["gates"]["can_accept_l2_2"] = True
    forged["gates"]["can_start_clock"] = True
    forged["gates"]["can_close_l2_2"] = True
    names = set(l2.validate_report(forged))
    assert "additive_historical_shorts" in names
    assert "forged_pass" in names
    assert "production_claim" in names
    assert "forged_accept" in names
    assert "forged_clock_start" in names
    assert "forged_close" in names
    assert honest["l2_2_status"] == "NOT_STARTED"
    assert honest["gates"]["can_start_clock"] is False


def test_sequential_soaks_and_wall_resets_are_not_one_continuous_72h():
    pair = l2.synthetic_sequential_soaks([86400.0, 86400.0], pid_base=8100)
    assessed = l2.assess_process_continuity(pair)
    assert assessed["invocation_count"] == 2
    assert assessed["distinct_start_count"] == 2
    assert assessed["distinct_process_count"] == 2
    assert assessed["same_host"] is True
    assert assessed["back_to_back"] is True
    assert assessed["stitched_duration_seconds"] == 172800.0
    assert assessed["calendar_span_seconds"] == 172800.0
    assert assessed["stitched_duration_reaches_259200"] is False
    assert assessed["counts_toward_gate"] is False
    assert assessed["sequential_soaks_are_continuous"] is False
    assert assessed["stitched_processes_count_toward_gate"] is False
    assert assessed["single_live_process"] is False

    trio = l2.assess_process_continuity(l2.synthetic_sequential_soaks([86400.0, 86400.0, 86400.0], pid_base=8200))
    assert trio["invocation_count"] == 3
    assert trio["stitched_duration_seconds"] == 259200.0
    assert trio["calendar_span_seconds"] == 259200.0
    assert trio["stitched_duration_reaches_259200"] is True
    assert trio["calendar_span_reaches_259200"] is True
    assert trio["same_host"] is True
    assert trio["back_to_back"] is True
    assert trio["counts_toward_gate"] is False
    assert trio["sequential_soaks_are_continuous"] is False
    assert trio["stitched_processes_count_toward_gate"] is False

    reset = l2.assess_process_continuity([], wall_samples=[0.0, 86400.0, 0.0, 86400.0, 0.0, 86400.0])
    assert reset["wall_reset"] is True
    assert reset["segment_count"] == 3
    assert reset["stitched_duration_seconds"] == 259200.0
    assert reset["stitched_duration_reaches_259200"] is True
    assert reset["calendar_span_seconds"] is None
    assert reset["counts_toward_gate"] is False
    assert reset["sequential_soaks_are_continuous"] is False
    assert reset["stitched_processes_count_toward_gate"] is False

    standing = l2.standing_process_continuity(None)
    assert standing["stitch_claim"] is False
    assert standing["sequential_soaks_are_continuous"] is False
    assert standing["stitched_processes_count_toward_gate"] is False
    assert standing["counts_toward_gate"] is False
    report = l2.score(_load("scaffold_clock_not_started.json"))
    assert report["process_continuity"] == standing
    assert report["wall"]["stitch_claim"] is False
    assert report["l2_2_status"] == "NOT_STARTED"
    assert report["clock_state"] == "NOT_STARTED"
    assert report["gates"]["can_start_clock"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"


def _stitch_capture(invocations: list[dict] | None = None, *, elapsed: float = 259200.0) -> dict:
    doc = _load("scaffold_full_wall_cannot_accept.json")
    doc["note"] = "In-memory stitch of ended soak invocations. Not one live 72h process."
    doc["wall"]["elapsed_seconds"] = elapsed
    doc["wall"]["source"] = "monotonic"
    doc["metrics"]["wall_elapsed_s"] = elapsed
    if invocations is not None:
        doc["wall"]["invocations"] = invocations
    return doc


def test_stitched_restarted_or_reset_wall_does_not_count_as_72h():
    pair = _stitch_capture(l2.synthetic_sequential_soaks([86400.0, 86400.0], pid_base=8100), elapsed=172800.0)
    report = l2.score(pair)
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["clock_state"] == "INCOMPLETE"
    assert report["wall"]["counts_toward_gate"] is False
    assert report["wall"]["elapsed_meets_259200"] is False
    assert report["wall"]["stitch_claim"] is True
    assert report["process_continuity"]["sequential_soaks_are_continuous"] is False
    assert report["process_continuity"]["stitched_processes_count_toward_gate"] is False
    assert report["process_continuity"]["counts_toward_gate"] is False
    assert report["process_continuity"]["same_host"] is True
    assert report["process_continuity"]["back_to_back"] is True
    assert report["process_continuity"]["distinct_start_count"] == 2
    assert report["process_continuity"]["distinct_process_count"] == 2
    assert report["process_continuity"]["stitched_duration_seconds"] == 172800.0
    assert report["process_continuity"]["stitched_duration_reaches_259200"] is False
    assert "stitched_process_boundaries" in report["gates"]["blockers"]
    assert report["gates"]["can_start_clock"] is False
    assert report["gates"]["can_accept_l2_2"] is False
    assert report["gates"]["can_close_l2_2"] is False
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert l2.validate_report(report) == []

    gapped = l2.synthetic_sequential_soaks([86400.0, 86400.0], pid_base=8300)
    gapped[1]["start_utc"] = "2026-02-02T01:00:00Z"
    gapped[1]["end_utc"] = "2026-02-03T01:00:00Z"
    report = l2.score(_stitch_capture(gapped, elapsed=172800.0))
    assert report["process_continuity"]["back_to_back"] is False
    assert report["process_continuity"]["calendar_span_seconds"] == 176400.0
    assert report["process_continuity"]["counts_toward_gate"] is False
    assert report["process_continuity"]["sequential_soaks_are_continuous"] is False
    assert report["clock_state"] == "INCOMPLETE"

    trio = _stitch_capture(l2.synthetic_sequential_soaks([86400.0, 86400.0, 86400.0], pid_base=8200), elapsed=259200.0)
    trio["wall"]["source"] = "stitched"
    trio["claimed_l2_2_status"] = "PASS"
    trio["claimed_production_7x24"] = "ACCEPTED"
    report = l2.score(trio)
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["clock_state"] == "INCOMPLETE"
    assert report["wall"]["counts_toward_gate"] is False
    assert report["bars"]["wall_monotonic_72h"] is False
    assert report["process_continuity"]["stitched_duration_seconds"] == 259200.0
    assert report["process_continuity"]["calendar_span_seconds"] == 259200.0
    assert report["process_continuity"]["stitched_duration_reaches_259200"] is True
    assert report["process_continuity"]["calendar_span_reaches_259200"] is True
    assert report["process_continuity"]["counts_toward_gate"] is False
    assert report["process_continuity"]["sequential_soaks_are_continuous"] is False
    assert report["process_continuity"]["stitched_processes_count_toward_gate"] is False
    assert "stitched_process_boundaries" in report["gates"]["blockers"]
    assert "forged_claim_ignored" in report["gates"]["blockers"]
    assert report["production_7x24"] == "NOT_ACCEPTED"
    assert report["gates"]["can_accept_l2_2"] is False
    assert l2.validate_report(report) == []

    reset = _stitch_capture(elapsed=259200.0)
    reset["wall"]["wall_samples"] = [0, 86400, 0, 86400, 0, 86400]
    report = l2.score(reset)
    assert report["process_continuity"]["wall_reset"] is True
    assert report["process_continuity"]["segment_count"] == 3
    assert report["process_continuity"]["stitched_duration_seconds"] == 259200.0
    assert report["process_continuity"]["counts_toward_gate"] is False
    assert report["wall"]["counts_toward_gate"] is False
    assert report["clock_state"] == "INCOMPLETE"
    assert report["l2_2_status"] == "INCOMPLETE"

    pids = _stitch_capture(elapsed=259200.0)
    pids["wall"]["pids"] = [4101, 4102]
    report = l2.score(pids)
    assert report["process_continuity"]["distinct_process_count"] == 2
    assert report["process_continuity"]["stitch_claim"] is True
    assert report["process_continuity"]["stitched_duration_reaches_259200"] is True
    assert report["process_continuity"]["counts_toward_gate"] is False
    assert report["process_continuity"]["stitched_processes_count_toward_gate"] is False
    assert report["clock_state"] == "INCOMPLETE"

    starts = _stitch_capture(elapsed=259200.0)
    starts["wall"]["starts"] = ["2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z"]
    report = l2.score(starts)
    assert report["process_continuity"]["distinct_start_count"] == 2
    assert report["process_continuity"]["counts_toward_gate"] is False
    assert report["process_continuity"]["sequential_soaks_are_continuous"] is False
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["gates"]["can_start_clock"] is False

    single = _stitch_capture(
        [
            {
                "start_utc": "2026-02-01T00:00:00Z",
                "end_utc": "2026-02-04T00:00:00Z",
                "pid": 1,
                "wall_elapsed_s": 259200.004,
                "host": "fixture-host",
            }
        ],
        elapsed=259200.004,
    )
    report = l2.score(single)
    assert report["process_continuity"]["stitch_claim"] is False
    assert report["clock_state"] == "WALL_OBSERVED"
    assert report["wall"]["counts_toward_gate"] is True
    assert report["l2_2_status"] == "INCOMPLETE"
    assert report["gates"]["can_accept_l2_2"] is False


def test_forged_stitch_report_fails_closed():
    honest = l2.score(_load("scaffold_clock_not_started.json"))
    forged = json.loads(json.dumps(honest))
    forged["process_continuity"]["sequential_soaks_are_continuous"] = True
    forged["process_continuity"]["stitched_processes_count_toward_gate"] = True
    forged["process_continuity"]["counts_toward_gate"] = True
    forged["process_continuity"]["stitch_claim"] = True
    forged["wall"]["invocations"] = l2.synthetic_sequential_soaks([86400.0, 86400.0, 86400.0], pid_base=8200)
    forged["wall"]["counts_toward_gate"] = True
    forged["wall"]["stitch_claim"] = True
    forged["wall"]["source"] = "stitched"
    forged["wall"]["elapsed_seconds"] = 259200
    forged["l2_2_status"] = "PASS"
    forged["clock_state"] = "WALL_OBSERVED"
    forged["production_7x24"] = "ACCEPTED"
    forged["gates"]["can_accept_l2_2"] = True
    forged["gates"]["can_start_clock"] = True
    forged["gates"]["can_close_l2_2"] = True
    names = set(l2.validate_report(forged))
    assert "stitched_process_boundaries" in names
    assert "forged_pass" in names
    assert "production_claim" in names
    assert "forged_accept" in names
    assert "forged_clock_start" in names
    assert "forged_close" in names
    assert honest["l2_2_status"] == "NOT_STARTED"
    assert honest["clock_state"] == "NOT_STARTED"
    assert honest["process_continuity"]["sequential_soaks_are_continuous"] is False
    assert honest["process_continuity"]["stitched_processes_count_toward_gate"] is False
    assert honest["gates"]["can_start_clock"] is False
