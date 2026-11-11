"""Sample start-readiness aggregate. It does not satisfy any founder condition."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import start_readiness as ready  # noqa: E402


def _assert_closed(row: dict) -> None:
    assert row["condition_1_satisfied"] is False
    assert row["condition_2_satisfied"] is False
    assert row["condition_3_satisfied"] is False
    assert row["condition_4_satisfied"] is False
    assert row["condition_5_satisfied"] is False
    assert row["dummy_tests_satisfy_condition_5"] is False
    assert row["implementation_satisfies_condition_5"] is False
    assert row["sample_passes_satisfy_any_founder_condition"] is False
    assert row["all_five_conditions_satisfied"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["a_72h_result_is_production_readiness"] is False
    assert row["a_72h_pass_is_production_readiness"] is False
    assert row["ubuntu_24h_short_wall_is_production_readiness"] is False
    assert row["ubuntu_24h_counts_as_72h"] is False
    assert row["is_a_start"] is False
    assert row["soak_launched"] is False
    assert row["demonstrates_10_minute_supervision_cadence"] is False
    assert row["is_supervisor_watchdog_of_live_supervisor"] is False
    assert row["packs_live_soak_evidence"] is False
    assert row["attributes_live_soak_failure"] is False


def test_honest_sample_is_accepted_and_does_not_satisfy_condition_5():
    for spec in ready.SAMPLE_SPECS:
        if spec["accepted"] is not True:
            continue
        decision = ready.assess_report(spec["report"])
        assert decision["accepted"] is True
        assert decision["rejection"] is None
        assert decision["sample_only"] is True
        assert decision["offline"] is True
        _assert_closed(decision)
        assert decision["rejects_production_claim_from_sample"] is False
        assert decision["aggregates_sample_checkers_passed"] is False


def test_production_claims_and_72h_readiness_are_refused():
    refused = {
        "production_accepted": "production_claim",
        "production_pass": "production_claim",
        "production_ready": "production_claim",
        "seventy_two_hour_called_readiness": "72h_as_production_readiness",
        "ubuntu_short_called_readiness": "short_wall_as_production_readiness",
        "condition_5_called_satisfied": "condition_5_claimed",
        "or_sample_passes_into_conditions": "sample_passes_promoted",
        "and_sample_passes_into_can_start_clock": "sample_passes_promoted",
    }
    by_id = {spec["id"]: spec for spec in ready.SAMPLE_SPECS}
    for name, rejection in refused.items():
        decision = ready.assess_report(by_id[name]["report"])
        assert decision["accepted"] is False
        assert decision["rejection"] == rejection
        _assert_closed(decision)


def test_or_and_compositions_fail_closed():
    passes = {flag: True for flag in ready.SAMPLE_PASS_FLAGS if flag != "aggregates_sample_checkers_passed"}
    for mode in ("or", "and"):
        forbidden = ready.forbidden_composition(passes, mode)
        assert forbidden["condition_1_satisfied"] is True
        assert forbidden["condition_5_satisfied"] is True
        assert forbidden["can_start_clock"] is True
        assert forbidden["all_five_conditions_satisfied"] is True
        decision = ready.assess_report(forbidden)
        assert decision["accepted"] is False
        assert decision["rejection"] == "sample_passes_promoted"
        _assert_closed(decision)
        assert decision["can_start_clock"] is False
        assert decision["condition_5_satisfied"] is False


def test_sample_exercise_aggregates_without_satisfying_any_condition():
    status = ready.stable_scaffold_status()
    assert status["ok"] is True
    assert status["detail"] == "implementation_exists_sample_checkers_aggregated"
    assert status["tool"] == "scripts/start_readiness.py"
    assert status["action"] == "aggregate_sample_checkers"
    assert status["dut"] == "synthetic_sample_readiness"
    assert status["founder_condition_id"] == "not_production_7x24"
    assert status["sample_only"] is True
    assert status["offline"] is True
    assert status["aggregates_sample_checkers_passed"] is True
    assert status["rejects_production_claim_from_sample"] is True
    assert status["refuses_72h_as_production_readiness"] is True
    assert status["or_composition_refused"] is True
    assert status["and_composition_refused"] is True
    assert status["ubuntu_24h_wall_seconds"] == 86400.001
    assert status["wall_72h_seconds"] == 259200
    _assert_closed(status)
    assert ready.scaffold_violations(status) == []
    by_id = {row["id"]: row for row in status["samples"]}
    assert by_id["honest_not_accepted"]["accepted"] is True
    assert by_id["production_accepted"]["rejection"] == "production_claim"
    assert by_id["production_pass"]["rejection"] == "production_claim"
    assert by_id["production_ready"]["rejection"] == "production_claim"
    assert by_id["seventy_two_hour_called_readiness"]["rejection"] == "72h_as_production_readiness"
    assert by_id["ubuntu_short_called_readiness"]["rejection"] == "short_wall_as_production_readiness"
    assert by_id["honest_ubuntu_short_is_not_production"]["accepted"] is True
    assert by_id["honest_ubuntu_short_is_not_production"]["ubuntu_24h_counts_as_72h"] is False
    for row in status["compositions"]:
        assert row["accepted"] is False
        assert row["rejection"] == "sample_passes_promoted"
        assert row["promoted_can_start_clock"] is True
        assert row["promoted_condition_1"] is True
        assert row["promoted_condition_5"] is True
        _assert_closed(row)
    checkers = status["checkers"]
    assert checkers["supervision_policy"]["classifies_sample_policy_bands_passed"] is True
    assert checkers["supervision_policy"]["condition_1_satisfied"] is False
    assert checkers["supervision_cadence"]["writes_on_schedule_passed"] is True
    assert checkers["supervision_cadence"]["demonstrates_10_minute_supervision_cadence"] is False
    assert checkers["supervision_cadence"]["condition_2_satisfied"] is False
    assert checkers["supervisor_watchdog"]["dummy_crash_within_10s_passed"] is True
    assert checkers["supervisor_watchdog"]["is_supervisor_watchdog_of_live_supervisor"] is False
    assert checkers["public_evidence_pack"]["classifies_or_validates_sample_public_pack_passed"] is True
    assert checkers["public_evidence_pack"]["packs_live_soak_evidence"] is False
    assert checkers["public_evidence_pack"]["condition_3_satisfied"] is False
    assert checkers["failure_attribution"]["classifies_sample_attributions_passed"] is True
    assert checkers["failure_attribution"]["attributes_live_soak_failure"] is False
    assert checkers["failure_attribution"]["condition_4_satisfied"] is False
    blob = json.dumps(status)
    assert '"condition_5_satisfied": true' not in blob
    assert '"all_five_conditions_satisfied": true' not in blob
    assert '"sample_passes_satisfy_any_founder_condition": true' not in blob
    assert '"can_start_clock": true' not in blob
    forged = json.loads(blob)
    forged["condition_5_satisfied"] = True
    forged["all_five_conditions_satisfied"] = True
    forged["sample_passes_satisfy_any_founder_condition"] = True
    forged["can_start_clock"] = True
    forged["production_7x24"] = "ACCEPTED"
    forged["l2_2_status"] = "PASS"
    names = set(ready.scaffold_violations(forged))
    assert "condition_5_unsatisfied" in names
    assert "sample_passes_do_not_satisfy_conditions" in names
    assert "forged_clock_start" in names
    assert "production_claim" in names
    assert "forged_pass" in names


def test_a_pretend_claim_does_not_open_condition_5_or_the_clock():
    block = ready.stable_scaffold_status()
    ready.annotate_scaffold_claim(
        block,
        {
            "composition": "or",
            "classifies_sample_policy_bands_passed": True,
            "writes_on_schedule_passed": True,
            "dummy_crash_within_10s_passed": True,
            "classifies_or_validates_sample_public_pack_passed": True,
            "classifies_sample_attributions_passed": True,
            "rejects_production_claim_from_sample": True,
            "refuses_72h_as_production_readiness": True,
            "aggregates_sample_checkers_passed": True,
            "condition_1_satisfied": True,
            "condition_2_satisfied": True,
            "condition_3_satisfied": True,
            "condition_4_satisfied": True,
            "condition_5_satisfied": True,
            "all_five_conditions_satisfied": True,
            "sample_passes_satisfy_any_founder_condition": True,
            "dummy_tests_satisfy_condition_5": True,
            "implementation_satisfies_condition_5": True,
            "can_start_clock": True,
            "production_7x24": "ACCEPTED",
            "wall_seconds": 86400.001,
            "experiment": "UBUNTU-24H",
            "ubuntu_24h_short_wall_is_production_readiness": True,
            "a_72h_result_is_production_readiness": True,
            "l2_2_status": "PASS",
            "clock_state": "STARTED",
        },
    )
    ready.apply_closed_flags(block)
    assert block["sample_passes_or_into_condition"] is True
    assert block["sample_passes_and_into_clock"] is True
    assert block["condition_5_claimed"] is True
    assert block["production_claim_from_sample"] is True
    assert block["seventy_two_hour_called_production_readiness"] is True
    assert block["short_wall_called_production_readiness"] is True
    assert block["pass_or_start_claimed"] is True
    assert block["aggregates_sample_checkers_passed"] is True
    assert block["rejects_production_claim_from_sample"] is True
    assert block["refuses_72h_as_production_readiness"] is True
    _assert_closed(block)
    assert ready.scaffold_violations(block) == []


def test_cli_samples_do_not_start_the_clock():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "start_readiness.py"), "--samples"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["aggregates_sample_checkers_passed"] is True
    assert payload["rejects_production_claim_from_sample"] is True
    assert payload["refuses_72h_as_production_readiness"] is True
    assert payload["condition_5_satisfied"] is False
    assert payload["can_start_clock"] is False
    _assert_closed(payload)
    one = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "start_readiness.py"),
            "--report",
            json.dumps({"sample_only": True, "offline": True, "production_7x24": "ACCEPTED"}),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert one.returncode == 0, one.stderr
    rejected = json.loads(one.stdout)
    assert rejected["accepted"] is False
    assert rejected["rejection"] == "production_claim"
    assert rejected["aggregates_sample_checkers_passed"] is False
    assert rejected["condition_5_satisfied"] is False
    _assert_closed(rejected)
