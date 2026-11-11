"""Sample failure attribution. It does not satisfy founder condition 4."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import failure_attribution as attribution  # noqa: E402


def _assert_closed(row: dict) -> None:
    assert row["condition_4_satisfied"] is False
    assert row["sample_classification_satisfies_condition_4"] is False
    assert row["dummy_tests_satisfy_condition_4"] is False
    assert row["implementation_satisfies_condition_4"] is False
    assert row["attributes_live_soak_failure"] is False
    assert row["unknown_root_cause_allowed"] is False
    assert row["condition_2_satisfied"] is False
    assert row["demonstrates_10_minute_supervision_cadence"] is False
    assert row["is_supervisor_watchdog_of_live_supervisor"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["is_a_start"] is False
    assert row["soak_launched"] is False


def test_each_accepted_class_passes_and_does_not_open_condition_4():
    business = attribution.classify_record({"terminal_class": "business", "example": "verifier reject"})
    host = attribution.classify_record({"example": "reboot"})
    supervision = attribution.classify_record({"example": "gap past red without DUT fault"})
    assert business["accepted"] is True and business["terminal_class"] == "business"
    assert host["accepted"] is True and host["terminal_class"] == "host"
    assert supervision["accepted"] is True and supervision["terminal_class"] == "supervision"
    for row in (business, host, supervision):
        _assert_closed(row)
        assert row["rejection"] is None
        assert row["sample_only"] is True
    examples = {
        "task fail": "business",
        "budget block": "business",
        "WT/Explorer storm": "host",
        "disk full": "host",
        "OOM": "host",
        "power": "host",
        "wrong watch file": "supervision",
        "monitor crash": "supervision",
    }
    for example, terminal in examples.items():
        classified = attribution.classify_record({"example": example})
        assert classified["accepted"] is True
        assert classified["terminal_class"] == terminal
        _assert_closed(classified)


def test_unknown_empty_missing_free_text_and_multiple_classes_are_rejected():
    unknown = attribution.classify_record({"terminal_class": "unknown"})
    phrase = attribution.classify_record({"root_cause": "unknown root cause"})
    empty = attribution.classify_record({"terminal_class": ""})
    blank = attribution.classify_record("")
    missing = attribution.classify_record({})
    absent = attribution.classify_record(None)
    free_text = attribution.classify_record({"root_cause": "cosmic rays"})
    multiple = attribution.classify_record({"classes": ["business", "host"]})
    extra = attribution.classify_record(
        {"terminal_class": "business", "classes": ["business", "supervision"]}
    )
    allowed = attribution.classify_record(
        {"terminal_class": "host", "unknown_root_cause_allowed": True}
    )
    assert unknown["accepted"] is False and unknown["rejection"] == "unknown"
    assert phrase["rejection"] == "unknown"
    assert empty["rejection"] == "empty"
    assert blank["rejection"] == "empty"
    assert missing["rejection"] == "missing"
    assert absent["rejection"] == "missing"
    assert free_text["rejection"] == "free_text"
    assert multiple["rejection"] == "multiple_classes"
    assert multiple["terminal_class"] is None
    assert extra["rejection"] == "multiple_classes"
    assert allowed["rejection"] == "unknown"
    for row in (unknown, phrase, empty, blank, missing, absent, free_text, multiple, extra, allowed):
        _assert_closed(row)
        assert row["accepted"] is False


def test_sample_exercise_passes_without_satisfying_condition_4():
    status = attribution.stable_scaffold_status()
    assert status["ok"] is True
    assert status["detail"] == "implementation_exists_sample_attributions_classified"
    assert status["classifies_sample_attributions_passed"] is True
    assert status["unknown_root_cause_rejected"] is True
    assert status["empty_root_cause_rejected"] is True
    assert status["missing_root_cause_rejected"] is True
    assert status["free_text_root_cause_rejected"] is True
    assert status["multiple_classes_rejected"] is True
    assert status["tool"] == "scripts/failure_attribution.py"
    assert status["dut"] == "synthetic_attribution_records"
    _assert_closed(status)
    assert attribution.scaffold_violations(status) == []
    classes = {row["terminal_class"] for row in status["samples"] if row["accepted"] is True}
    assert classes == {"business", "host", "supervision"}
    blob = json.dumps(status)
    assert '"condition_4_satisfied": true' not in blob
    assert '"can_start_clock": true' not in blob
    assert '"l2_2_status": "PASS"' not in blob
    assert '"production_7x24": "ACCEPTED"' not in blob
    forged = json.loads(blob)
    forged["condition_4_satisfied"] = True
    forged["attributes_live_soak_failure"] = True
    forged["can_start_clock"] = True
    forged["l2_2_status"] = "PASS"
    names = set(attribution.scaffold_violations(forged))
    assert "condition_4_unsatisfied" in names
    assert "forged_clock_start" in names
    assert "forged_pass" in names


def test_a_pretend_claim_does_not_open_condition_4():
    block = attribution.stable_scaffold_status()
    attribution.annotate_scaffold_claim(
        block,
        {
            "condition_4_satisfied": True,
            "dummy_tests_satisfy_condition_4": True,
            "implementation_satisfies_condition_4": True,
            "attributes_live_soak_failure": True,
            "unknown_root_cause_allowed": True,
            "classes": ["business", "host"],
            "l2_2_status": "PASS",
            "clock_state": "STARTED",
            "can_start_clock": True,
            "production_7x24": "ACCEPTED",
        },
    )
    attribution.apply_closed_flags(block)
    assert block["sample_classification_claimed_as_condition_4"] is True
    assert block["unknown_root_cause_called_terminal"] is True
    assert block["multiple_classes_called_terminal"] is True
    assert block["live_soak_attribution_claimed"] is True
    assert block["pass_or_start_claimed"] is True
    _assert_closed(block)
    assert attribution.scaffold_violations(block) == []


def test_cli_samples_do_not_start_the_clock():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "failure_attribution.py"), "--samples"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["classifies_sample_attributions_passed"] is True
    assert payload["unknown_root_cause_rejected"] is True
    _assert_closed(payload)
    one = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "failure_attribution.py"),
            "--record",
            "unknown",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert one.returncode == 0, one.stderr
    rejected = json.loads(one.stdout)
    assert rejected["accepted"] is False
    assert rejected["rejection"] == "unknown"
    assert rejected["unknown_root_cause_rejected"] is True
    _assert_closed(rejected)
