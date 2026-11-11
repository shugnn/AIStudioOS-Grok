"""Sample supervision-policy checks. They do not satisfy founder condition 1."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_gap_log as gaplog  # noqa: E402
import supervision_policy as policy  # noqa: E402

JUST_ABOVE = math.nextafter(300.0, math.inf)


def _assert_closed(row: dict) -> None:
    assert row["condition_1_satisfied"] is False
    assert row["sample_policy_satisfies_condition_1"] is False
    assert row["dummy_tests_satisfy_condition_1"] is False
    assert row["implementation_satisfies_condition_1"] is False
    assert row["committed_constants_satisfy_condition_1"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["is_a_start"] is False
    assert row["soak_launched"] is False
    assert row["condition_2_satisfied"] is False
    assert row["condition_3_satisfied"] is False
    assert row["condition_4_satisfied"] is False


def test_committed_constants_match_the_founder_bands_without_satisfying_condition_1():
    assert gaplog.YELLOW_MIN_SECONDS == 13.0
    assert gaplog.RED_MIN_SECONDS == 300.0
    assert policy.committed_bands_match_founder_policy() is True
    assert policy.monitor_source_records_mono_seconds() is True
    for seconds, band in (
        (12.0, "ok"),
        (13.0, "yellow"),
        (300.0, "yellow"),
        (JUST_ABOVE, "red"),
    ):
        assert gaplog.classify_band(seconds) == band
        decision = policy.classify_sample_gap(seconds)
        assert decision["accepted"] is True
        assert decision["band"] == band
        assert decision["rejection"] is None
        _assert_closed(decision)


def test_a_non_decreasing_sequence_passes_and_a_backward_jump_is_refused():
    forward = policy.assess_sequence(
        [
            {"timestamp": "2026-02-01T00:00:00Z", "mono_seconds": 0.0},
            {"timestamp": "2026-02-01T00:00:13Z", "mono_seconds": 13.0},
            {"timestamp": "2026-02-01T00:05:00Z", "mono_seconds": 300.0},
        ]
    )
    assert forward["accepted"] is True
    assert forward["rejection"] is None
    _assert_closed(forward)
    wall = policy.assess_sequence(
        [
            {"timestamp": "2026-02-01T00:05:00Z", "mono_seconds": 300.0},
            {"timestamp": "2026-02-01T00:04:00Z", "mono_seconds": 301.0},
        ]
    )
    assert wall["accepted"] is False
    assert wall["rejection"] == "backward_jump"
    assert wall["jumped"] == "timestamp"
    assert wall["backward_clock_is_monotonic"] is False
    _assert_closed(wall)
    mono = policy.assess_sequence(
        [
            {"mono_seconds": 20.0},
            {"mono_seconds": 19.0},
        ]
    )
    assert mono["accepted"] is False
    assert mono["rejection"] == "backward_jump"
    assert mono["jumped"] == "mono_seconds"
    _assert_closed(mono)


def test_a_different_band_policy_is_refused():
    yellow_10 = policy.assess_policy(
        {
            "yellow_min_seconds": 10.0,
            "yellow_max_seconds": 300.0,
            "red_exclusive_min_seconds": 300.0,
            "clock": "monotonic",
        }
    )
    assert yellow_10["accepted"] is False
    assert yellow_10["rejection"] == "band_mismatch"
    assert yellow_10["matches_founder_policy"] is False
    _assert_closed(yellow_10)
    inclusive = policy.assess_policy(
        {
            "yellow_min_seconds": 13.0,
            "yellow_max_seconds": 300.0,
            "red_exclusive_min_seconds": 300.0,
            "red_inclusive": True,
            "clock": "monotonic",
        }
    )
    assert inclusive["accepted"] is False
    assert inclusive["rejection"] == "red_inclusive"
    assert gaplog.classify_band(300.0) == "yellow"
    _assert_closed(inclusive)
    called = policy.assess_policy(
        {
            "yellow_min_seconds": 13.0,
            "yellow_max_seconds": 300.0,
            "red_exclusive_min_seconds": 300.0,
            "clock": "monotonic",
            "condition_1_satisfied": True,
            "committed_constants_satisfy_condition_1": True,
        }
    )
    assert called["accepted"] is False
    assert called["rejection"] == "condition_1_claimed"
    assert called["condition_1_satisfied"] is False
    assert called["committed_constants_satisfy_condition_1"] is False


def test_sample_exercise_passes_without_satisfying_condition_1():
    status = policy.stable_scaffold_status()
    assert status["ok"] is True
    assert status["detail"] == "implementation_exists_sample_policy_classified"
    assert status["classifies_sample_policy_bands_passed"] is True
    assert status["monotonic_sample_sequence_passed"] is True
    assert status["declared_bands_match_founder_policy"] is True
    assert status["backward_jump_rejected"] is True
    assert status["alternate_bands_rejected"] is True
    assert status["red_inclusive_rejected"] is True
    assert status["condition_1_claim_rejected"] is True
    assert status["sample_only"] is True
    assert status["offline"] is True
    assert status["tool"] == "scripts/supervision_policy.py"
    assert status["gap_logger"] == "scripts/coverage_gap_log.py"
    assert status["yellow_min_seconds"] == 13.0
    assert status["red_exclusive_min_seconds"] == 300.0
    assert status["red_boundary"] == "exclusive"
    _assert_closed(status)
    assert policy.scaffold_violations(status) == []
    by_id = {row["id"]: row for row in status["samples"]}
    assert by_id["gap_12_ok"]["band"] == "ok"
    assert by_id["gap_13_yellow"]["band"] == "yellow"
    assert by_id["gap_300_yellow"]["band"] == "yellow"
    assert by_id["gap_just_above_300_red"]["band"] == "red"
    assert by_id["gap_just_above_300_red"]["gap_seconds"] > 300.0
    assert by_id["wall_clock_backward"]["rejection"] == "backward_jump"
    assert by_id["yellow_starts_at_10"]["rejection"] == "band_mismatch"
    assert by_id["red_inclusive_at_300"]["rejection"] == "red_inclusive"
    assert by_id["constants_called_condition_1"]["rejection"] == "condition_1_claimed"
    assert by_id["founder_numbers_not_condition_1"]["accepted"] is True
    assert by_id["founder_numbers_not_condition_1"]["condition_1_satisfied"] is False
    blob = json.dumps(status)
    assert '"condition_1_satisfied": true' not in blob
    assert '"committed_constants_satisfy_condition_1": true' not in blob
    assert '"can_start_clock": true' not in blob
    forged = json.loads(blob)
    forged["condition_1_satisfied"] = True
    forged["committed_constants_satisfy_condition_1"] = True
    forged["can_start_clock"] = True
    forged["l2_2_status"] = "PASS"
    names = set(policy.scaffold_violations(forged))
    assert "condition_1_unsatisfied" in names
    assert "forged_clock_start" in names
    assert "forged_pass" in names


def test_a_pretend_claim_does_not_open_condition_1():
    block = policy.stable_scaffold_status()
    policy.annotate_scaffold_claim(
        block,
        {
            "condition_1_satisfied": True,
            "dummy_tests_satisfy_condition_1": True,
            "implementation_satisfies_condition_1": True,
            "committed_constants_satisfy_condition_1": True,
            "yellow_min_seconds": 10.0,
            "red_inclusive": True,
            "clock": "wall",
            "l2_2_status": "PASS",
            "clock_state": "STARTED",
            "can_start_clock": True,
            "production_7x24": "ACCEPTED",
        },
    )
    policy.apply_closed_flags(block)
    assert block["sample_policy_claimed_as_condition_1"] is True
    assert block["committed_constants_claimed_as_condition_1"] is True
    assert block["alternate_bands_called_founder_policy"] is True
    assert block["backward_clock_called_monotonic"] is True
    assert block["pass_or_start_claimed"] is True
    assert block["classifies_sample_policy_bands_passed"] is True
    assert block["declared_bands_match_founder_policy"] is True
    _assert_closed(block)
    assert policy.scaffold_violations(block) == []


def test_cli_samples_do_not_start_the_clock():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "supervision_policy.py"), "--samples"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["classifies_sample_policy_bands_passed"] is True
    assert payload["monotonic_sample_sequence_passed"] is True
    assert payload["declared_bands_match_founder_policy"] is True
    assert payload["condition_1_satisfied"] is False
    _assert_closed(payload)
    one = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "supervision_policy.py"),
            "--policy",
            json.dumps({"yellow_min_seconds": 10, "yellow_max_seconds": 300, "red_exclusive_min_seconds": 300, "clock": "monotonic"}),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert one.returncode == 0, one.stderr
    rejected = json.loads(one.stdout)
    assert rejected["accepted"] is False
    assert rejected["rejection"] == "band_mismatch"
    assert rejected["classifies_sample_policy_bands_passed"] is False
    assert rejected["condition_1_satisfied"] is False
    _assert_closed(rejected)
