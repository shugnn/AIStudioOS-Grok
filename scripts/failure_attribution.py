#!/usr/bin/env python3
"""Sample three-way failure attribution.

Classifies synthetic attribution records into exactly one terminal class:
business, host, or supervision. Those names follow SUPERVISION_POLICY.md R7.

  business: verifier reject, task fail, budget block
  host: reboot, WT/Explorer storm, disk full, OOM, power
  supervision: wrong watch file, monitor crash, gap past red without DUT fault

Unknown, empty, missing, and other free-text labels are rejected. A record
that names more than one class is rejected, including when it has no single
terminal class. A passing classification is a sample exercise. It does not
attribute a live soak failure, it does not satisfy founder condition 4, and
it does not start the clock.

  python3 scripts/failure_attribution.py --samples
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

TOOL = "scripts/failure_attribution.py"
ACTION = "classify_sample_records"
DUT = "synthetic_attribution_records"
FOUNDER_CONDITION_ID = "three_way_attribution"
SUCCESS_DETAIL = "implementation_exists_sample_attributions_classified"
FAILURE_DETAILS = frozenset(
    {
        SUCCESS_DETAIL,
        "script_missing",
        "classification_failed",
        "import_failed",
    }
)
HOLE = "sample_classification_is_not_a_live_soak_failure_attribution"
NOTE = (
    "This module classifies sample attribution records only. "
    "Accepted terminal classes are business, host, and supervision. "
    "Unknown, empty, missing, and other free-text labels are rejected. "
    "A record that names more than one class without a single terminal class is rejected. "
    "Classifying these samples does not attribute a live soak failure, "
    "does not satisfy founder condition 4, and does not start L2-2."
)
TERMINAL_CLASSES = ("business", "host", "supervision")
TERMINAL_CLASS_SET = frozenset(TERMINAL_CLASSES)
TERMINAL_KEYS = ("terminal_class", "terminal", "class")
LIST_KEYS = ("classes", "ways", "named_classes")
TEXT_KEYS = ("example", "root_cause", "cause")
UNKNOWN_TOKENS = frozenset(
    {
        "unknown",
        "unknown root cause",
        "unknown root",
        "unspecified",
        "n a",
        "na",
        "tbd",
    }
)
EXAMPLE_TO_CLASS = {
    "verifier reject": "business",
    "task fail": "business",
    "budget block": "business",
    "reboot": "host",
    "wt explorer storm": "host",
    "disk full": "host",
    "oom": "host",
    "power": "host",
    "shell crash": "host",
    "wrong watch file": "supervision",
    "wrong watch target": "supervision",
    "monitor crash": "supervision",
    "gap past red without dut fault": "supervision",
    "gap red without dut fault": "supervision",
}
SAMPLE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "business_verifier_reject",
        "record": {"terminal_class": "business", "example": "verifier reject"},
        "accepted": True,
        "terminal_class": "business",
        "rejection": None,
    },
    {
        "id": "business_task_fail",
        "record": {"example": "task fail"},
        "accepted": True,
        "terminal_class": "business",
        "rejection": None,
    },
    {
        "id": "business_budget_block",
        "record": {"example": "budget block"},
        "accepted": True,
        "terminal_class": "business",
        "rejection": None,
    },
    {
        "id": "host_reboot",
        "record": {"terminal_class": "host", "example": "reboot"},
        "accepted": True,
        "terminal_class": "host",
        "rejection": None,
    },
    {
        "id": "host_wt_explorer_storm",
        "record": {"example": "WT/Explorer storm"},
        "accepted": True,
        "terminal_class": "host",
        "rejection": None,
    },
    {
        "id": "host_disk_full",
        "record": {"example": "disk full"},
        "accepted": True,
        "terminal_class": "host",
        "rejection": None,
    },
    {
        "id": "host_oom",
        "record": {"example": "OOM"},
        "accepted": True,
        "terminal_class": "host",
        "rejection": None,
    },
    {
        "id": "host_power",
        "record": {"example": "power"},
        "accepted": True,
        "terminal_class": "host",
        "rejection": None,
    },
    {
        "id": "supervision_wrong_watch_file",
        "record": {"terminal_class": "supervision", "example": "wrong watch file"},
        "accepted": True,
        "terminal_class": "supervision",
        "rejection": None,
    },
    {
        "id": "supervision_monitor_crash",
        "record": {"example": "monitor crash"},
        "accepted": True,
        "terminal_class": "supervision",
        "rejection": None,
    },
    {
        "id": "supervision_gap_past_red",
        "record": {"example": "gap past red without DUT fault"},
        "accepted": True,
        "terminal_class": "supervision",
        "rejection": None,
    },
    {
        "id": "unknown_label",
        "record": {"terminal_class": "unknown"},
        "accepted": False,
        "terminal_class": None,
        "rejection": "unknown",
    },
    {
        "id": "unknown_root_cause_phrase",
        "record": {"root_cause": "unknown root cause"},
        "accepted": False,
        "terminal_class": None,
        "rejection": "unknown",
    },
    {
        "id": "empty_terminal",
        "record": {"terminal_class": ""},
        "accepted": False,
        "terminal_class": None,
        "rejection": "empty",
    },
    {
        "id": "missing_record",
        "record": {},
        "accepted": False,
        "terminal_class": None,
        "rejection": "missing",
    },
    {
        "id": "free_text_label",
        "record": {"root_cause": "cosmic rays"},
        "accepted": False,
        "terminal_class": None,
        "rejection": "free_text",
    },
    {
        "id": "multiple_classes_without_terminal",
        "record": {"classes": ["business", "host"]},
        "accepted": False,
        "terminal_class": None,
        "rejection": "multiple_classes",
    },
    {
        "id": "multiple_classes_with_extra",
        "record": {"terminal_class": "business", "classes": ["business", "supervision"]},
        "accepted": False,
        "terminal_class": None,
        "rejection": "multiple_classes",
    },
)
_CACHE: dict[str, Any] | None = None


def _norm(value: Any) -> str:
    text = str(value).strip().lower().replace("_", " ").replace("-", " ").replace("/", " ")
    text = text.replace(">", " ")
    return " ".join(text.split())


def _closed_flags() -> dict[str, Any]:
    return {
        "condition_4_satisfied": False,
        "sample_classification_satisfies_condition_4": False,
        "dummy_tests_satisfy_condition_4": False,
        "implementation_satisfies_condition_4": False,
        "attributes_live_soak_failure": False,
        "unknown_root_cause_allowed": False,
        "condition_2_satisfied": False,
        "offline_exercise_satisfies_condition_2": False,
        "time_compressed_exercise_satisfies_condition_2": False,
        "demonstrates_10_minute_supervision_cadence": False,
        "dummy_tests_satisfy_condition_2": False,
        "scaffold_satisfies_condition_2": False,
        "implementation_satisfies_condition_2": False,
        "is_supervisor_watchdog_of_live_supervisor": False,
        "is_live_l2_2_supervisor": False,
        "is_live_l2_2_supervisor_watchdog": False,
        "live_supervisor_process": False,
        "live_soak_process": False,
        "soak_launched": False,
        "documented_soak_argv_executed": False,
        "is_a_start": False,
        "binds_clock_start": False,
        "implies_l2_2_pass": False,
        "implies_l2_2_acceptance": False,
        "a_72h_pass_is_production_readiness": False,
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "production_7x24": "NOT_ACCEPTED",
    }


def apply_closed_flags(block: dict[str, Any]) -> dict[str, Any]:
    """Force the honesty flags. A claim cannot open them."""
    block.update(_closed_flags())
    return block


def _decision(accepted: bool, terminal: str | None, rejection: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "accepted": accepted is True,
        "terminal_class": terminal if accepted is True else None,
        "rejection": None if accepted is True else rejection,
        "sample_only": True,
        "attributes_live_soak_failure": False,
    }
    body.update(_closed_flags())
    return body


def _take(raw: Any, named: list[str], problems: list[str]) -> None:
    if raw is None:
        problems.append("missing")
        return
    if isinstance(raw, str) and raw.strip() == "":
        problems.append("empty")
        return
    if not isinstance(raw, str):
        problems.append("free_text")
        return
    token = _norm(raw)
    if token in UNKNOWN_TOKENS:
        problems.append("unknown")
        return
    if token in TERMINAL_CLASS_SET:
        named.append(token)
        return
    mapped = EXAMPLE_TO_CLASS.get(token)
    if mapped:
        named.append(mapped)
        return
    problems.append("free_text")


def classify_record(record: Any) -> dict[str, Any]:
    """Classify one sample record. Does not attribute a live soak failure."""
    if record is None:
        return _decision(False, None, "missing")
    if isinstance(record, str):
        if record.strip() == "":
            return _decision(False, None, "empty")
        record = {"terminal_class": record}
    if not isinstance(record, dict):
        return _decision(False, None, "free_text")
    has_signal = any(key in record for key in TERMINAL_KEYS + LIST_KEYS + TEXT_KEYS)
    if not has_signal:
        return _decision(False, None, "missing")
    if record.get("unknown_root_cause_allowed") is True:
        return _decision(False, None, "unknown")

    named: list[str] = []
    problems: list[str] = []
    for key in TERMINAL_KEYS:
        if key in record:
            _take(record.get(key), named, problems)
    for key in LIST_KEYS:
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            problems.append("missing")
        elif isinstance(value, str) and value.strip() == "":
            problems.append("empty")
        elif not isinstance(value, list):
            problems.append("free_text")
        elif len(value) == 0:
            problems.append("empty")
        else:
            for item in value:
                _take(item, named, problems)
    for key in TEXT_KEYS:
        if key in record:
            _take(record.get(key), named, problems)

    unique: list[str] = []
    for item in named:
        if item not in unique:
            unique.append(item)
    if len(unique) > 1:
        return _decision(False, None, "multiple_classes")
    if "unknown" in problems:
        return _decision(False, None, "unknown")
    if len(unique) == 1 and not problems:
        return _decision(True, unique[0], None)
    if "empty" in problems and "free_text" not in problems:
        return _decision(False, None, "empty")
    if "missing" in problems and "free_text" not in problems and not unique:
        return _decision(False, None, "missing")
    return _decision(False, None, "free_text")


def _sample_flags() -> dict[str, Any]:
    """Flags stored on each sample row. The shell keeps the full closed set."""
    closed = _closed_flags()
    keys = (
        "condition_4_satisfied",
        "attributes_live_soak_failure",
        "dummy_tests_satisfy_condition_4",
        "implementation_satisfies_condition_4",
        "unknown_root_cause_allowed",
        "condition_2_satisfied",
        "demonstrates_10_minute_supervision_cadence",
        "is_supervisor_watchdog_of_live_supervisor",
        "can_start_clock",
        "can_accept_l2_2",
        "can_close_l2_2",
        "l2_2_status",
        "clock_state",
        "production_7x24",
        "is_a_start",
        "soak_launched",
    )
    return {key: closed[key] for key in keys}


def _sample_row(spec: dict[str, Any], classified: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": spec["id"],
        "accepted": classified.get("accepted") is True,
        "terminal_class": classified.get("terminal_class"),
        "rejection": classified.get("rejection"),
        "sample_only": True,
    }
    row.update(_sample_flags())
    return row


def canonical_samples() -> list[dict[str, Any]]:
    """Classify the fixed sample set. No clock and no live soak."""
    rows: list[dict[str, Any]] = []
    for spec in SAMPLE_SPECS:
        classified = classify_record(spec["record"])
        rows.append(_sample_row(spec, classified))
    return rows


def samples_match(rows: Any) -> bool:
    if not isinstance(rows, list) or len(rows) != len(SAMPLE_SPECS):
        return False
    expected = canonical_samples()
    for got, want in zip(rows, expected):
        if not isinstance(got, dict):
            return False
        for key in ("id", "accepted", "terminal_class", "rejection", "sample_only"):
            if got.get(key) != want.get(key):
                return False
        for key, value in _sample_flags().items():
            if got.get(key) != value:
                return False
    return True


def run_offline_exercise() -> dict[str, Any]:
    """Classify the fixed samples. A pass does not satisfy founder condition 4."""
    rows = canonical_samples()
    by_id = {row["id"]: row for row in rows}
    accepted_classes = {row["terminal_class"] for row in rows if row["accepted"] is True}
    unknown_rejected = (
        by_id["unknown_label"]["accepted"] is False
        and by_id["unknown_label"]["rejection"] == "unknown"
        and by_id["unknown_root_cause_phrase"]["rejection"] == "unknown"
    )
    empty_rejected = by_id["empty_terminal"]["rejection"] == "empty"
    missing_rejected = by_id["missing_record"]["rejection"] == "missing"
    free_text_rejected = by_id["free_text_label"]["rejection"] == "free_text"
    multiple_rejected = (
        by_id["multiple_classes_without_terminal"]["rejection"] == "multiple_classes"
        and by_id["multiple_classes_with_extra"]["rejection"] == "multiple_classes"
    )
    flags_closed = all(row.get("condition_4_satisfied") is False and row.get("can_start_clock") is False for row in rows)
    ok = (
        accepted_classes == set(TERMINAL_CLASSES)
        and unknown_rejected
        and empty_rejected
        and missing_rejected
        and free_text_rejected
        and multiple_rejected
        and flags_closed
        and all(
            by_id[spec["id"]]["accepted"] is spec["accepted"]
            and by_id[spec["id"]]["terminal_class"] == spec["terminal_class"]
            and by_id[spec["id"]]["rejection"] == spec["rejection"]
            for spec in SAMPLE_SPECS
        )
    )
    if not ok:
        return {"ok": False, "detail": "classification_failed"}
    return {
        "ok": True,
        "detail": SUCCESS_DETAIL,
        "classifies_sample_attributions_passed": True,
        "unknown_root_cause_rejected": True,
        "empty_root_cause_rejected": True,
        "missing_root_cause_rejected": True,
        "free_text_root_cause_rejected": True,
        "multiple_classes_rejected": True,
        "samples": rows,
    }


def _refused_claims() -> list[dict[str, Any]]:
    common = _closed_flags()
    specs = (
        ("sample_classification_called_condition_4", "sample_classification_claimed_as_condition_4"),
        ("unknown_root_cause_called_terminal", "unknown_root_cause_called_terminal"),
        ("multiple_classes_called_single_terminal", "multiple_classes_called_terminal"),
        ("sample_called_live_soak_attribution", "live_soak_attribution_claimed"),
    )
    rows: list[dict[str, Any]] = []
    for label, flag in specs:
        row: dict[str, Any] = {"label": label, flag: True}
        row.update(common)
        rows.append(row)
    return rows


def _scaffold_shell(
    detail: str,
    *,
    ok: bool,
    implementation_present: bool,
    samples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if detail not in FAILURE_DETAILS:
        detail = "classification_failed"
    passed = ok is True and detail == SUCCESS_DETAIL
    block: dict[str, Any] = {
        "ok": passed,
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "detail": detail,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "implementation_present": implementation_present and passed,
        "classifies_sample_attributions_passed": passed,
        "unknown_root_cause_rejected": passed,
        "empty_root_cause_rejected": passed,
        "missing_root_cause_rejected": passed,
        "free_text_root_cause_rejected": passed,
        "multiple_classes_rejected": passed,
        "accepted_terminal_classes": list(TERMINAL_CLASSES),
        "samples": samples if passed and isinstance(samples, list) else [],
        "hole": HOLE,
        "note": NOTE,
        "sample_classification_claimed_as_condition_4": False,
        "unknown_root_cause_called_terminal": False,
        "multiple_classes_called_terminal": False,
        "live_soak_attribution_claimed": False,
        "pass_or_start_claimed": False,
        "refused_claims": _refused_claims(),
    }
    block.update(_closed_flags())
    return block


def scaffold_status_for_root(script_present: bool) -> dict[str, Any]:
    """Skip classification when the inspected root has no classifier."""
    if not script_present:
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    return stable_scaffold_status()


def stable_scaffold_status(*, force: bool = False) -> dict[str, Any]:
    """Deterministic sample classification. No timings and no live soak."""
    global _CACHE
    if _CACHE is not None and not force:
        return json.loads(json.dumps(_CACHE))
    measured = run_offline_exercise()
    if measured.get("ok") is True and measured.get("detail") == SUCCESS_DETAIL:
        block = _scaffold_shell(
            SUCCESS_DETAIL,
            ok=True,
            implementation_present=True,
            samples=measured.get("samples"),
        )
        _CACHE = json.loads(json.dumps(block))
        return json.loads(json.dumps(block))
    return _scaffold_shell("classification_failed", ok=False, implementation_present=False)


def _claim_says_pass_or_start(claim: dict[str, Any]) -> bool:
    status = str(claim.get("l2_2_status") or "").strip().upper().replace(" ", "_")
    clock = str(claim.get("clock_state") or "").strip().upper().replace(" ", "_")
    production = str(claim.get("production_7x24") or "").strip().upper().replace(" ", "_")
    if status in {"PASS", "ACCEPTED", "STARTED"} or status.startswith("PASS"):
        return True
    if clock in {"STARTED", "WALL_OBSERVED"}:
        return True
    if production in {"ACCEPTED", "PASS", "PRODUCTION_ACCEPTED"} or "ACCEPTED" in production:
        return True
    return claim.get("can_start_clock") is True or claim.get("is_a_start") is True


def _claim_names_multiple_without_terminal(claim: dict[str, Any]) -> bool:
    if claim.get("multiple_classes_accepted") is True:
        return True
    classes = claim.get("classes")
    if not isinstance(classes, list):
        return False
    named = []
    for item in classes:
        token = _norm(item) if isinstance(item, str) else ""
        if token in TERMINAL_CLASS_SET and token not in named:
            named.append(token)
    if len(named) < 2:
        return claim.get("multiple_classes_accepted") is True
    terminal = claim.get("terminal_class", claim.get("terminal"))
    token = _norm(terminal) if isinstance(terminal, str) else ""
    return token not in TERMINAL_CLASS_SET


def annotate_scaffold_claim(block: dict[str, Any], claim: dict[str, Any] | None) -> None:
    """Record a pretense. Closed flags are applied again by the caller."""
    block["sample_classification_claimed_as_condition_4"] = False
    block["unknown_root_cause_called_terminal"] = False
    block["multiple_classes_called_terminal"] = False
    block["live_soak_attribution_claimed"] = False
    block["pass_or_start_claimed"] = False
    if not isinstance(claim, dict):
        return
    if (
        claim.get("condition_4_satisfied") is True
        or claim.get("sample_classification_satisfies_condition_4") is True
        or claim.get("dummy_tests_satisfy_condition_4") is True
        or claim.get("implementation_satisfies_condition_4") is True
    ):
        block["sample_classification_claimed_as_condition_4"] = True
    if claim.get("unknown_root_cause_allowed") is True or _norm(claim.get("terminal_class") or "") in UNKNOWN_TOKENS:
        block["unknown_root_cause_called_terminal"] = True
    if _claim_names_multiple_without_terminal(claim):
        block["multiple_classes_called_terminal"] = True
    if claim.get("attributes_live_soak_failure") is True:
        block["live_soak_attribution_claimed"] = True
    if _claim_says_pass_or_start(claim):
        block["pass_or_start_claimed"] = True


def _flag_violation(key: str) -> str:
    if key in {
        "condition_4_satisfied",
        "sample_classification_satisfies_condition_4",
        "dummy_tests_satisfy_condition_4",
        "implementation_satisfies_condition_4",
        "attributes_live_soak_failure",
        "unknown_root_cause_allowed",
    }:
        return "condition_4_unsatisfied"
    if key in {
        "condition_2_satisfied",
        "offline_exercise_satisfies_condition_2",
        "time_compressed_exercise_satisfies_condition_2",
        "demonstrates_10_minute_supervision_cadence",
        "dummy_tests_satisfy_condition_2",
        "scaffold_satisfies_condition_2",
        "implementation_satisfies_condition_2",
    }:
        return "condition_2_unsatisfied"
    if key in {
        "is_supervisor_watchdog_of_live_supervisor",
        "is_live_l2_2_supervisor",
        "is_live_l2_2_supervisor_watchdog",
        "live_supervisor_process",
        "live_soak_process",
    }:
        return "failure_attribution"
    if key in {"is_a_start", "binds_clock_start"}:
        return "offline_probe_is_not_a_start"
    if key == "can_start_clock":
        return "forged_clock_start"
    if key == "can_accept_l2_2":
        return "forged_accept"
    if key == "can_close_l2_2":
        return "forged_close"
    if key in {"implies_l2_2_pass", "l2_2_status"}:
        return "forged_pass"
    if key in {"a_72h_pass_is_production_readiness", "production_7x24", "implies_l2_2_acceptance"}:
        return "production_claim"
    if key in {"clock_state", "clock_effect"}:
        return "clock_state"
    if key in {"soak_launched", "documented_soak_argv_executed"}:
        return "soak_launched"
    return "failure_attribution"


def scaffold_violations(block: Any, *, require_success: bool = True) -> list[str]:
    """Reject a report that treats sample classification as founder condition 4."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["failure_attribution"]
    for key, expected in _closed_flags().items():
        if block.get(key) != expected:
            violations.append(_flag_violation(key))
    constants = {
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "hole": HOLE,
        "note": NOTE,
        "accepted_terminal_classes": list(TERMINAL_CLASSES),
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            violations.append("failure_attribution")
    for key in (
        "sample_classification_claimed_as_condition_4",
        "unknown_root_cause_called_terminal",
        "multiple_classes_called_terminal",
        "live_soak_attribution_claimed",
        "pass_or_start_claimed",
    ):
        if not isinstance(block.get(key), bool):
            violations.append("failure_attribution")
    claims = block.get("refused_claims")
    expected_labels = [
        "sample_classification_called_condition_4",
        "unknown_root_cause_called_terminal",
        "multiple_classes_called_single_terminal",
        "sample_called_live_soak_attribution",
    ]
    if not isinstance(claims, list):
        violations.append("failure_attribution")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if labels != expected_labels:
            violations.append("failure_attribution")
        else:
            flags = (
                "sample_classification_claimed_as_condition_4",
                "unknown_root_cause_called_terminal",
                "multiple_classes_called_terminal",
                "live_soak_attribution_claimed",
            )
            for item, flag in zip(claims, flags):
                if item.get(flag) is not True or item.get("condition_4_satisfied") is not False:
                    violations.append("condition_4_unsatisfied")
                if item.get("attributes_live_soak_failure") is not False:
                    violations.append("condition_4_unsatisfied")
                if item.get("l2_2_status") != "NOT_STARTED" or item.get("can_start_clock") is not False:
                    violations.append("offline_probe_is_not_a_start")
                if item.get("condition_2_satisfied") is not False:
                    violations.append("condition_2_unsatisfied")
    detail = block.get("detail")
    ok = block.get("ok")
    passed_keys = (
        "classifies_sample_attributions_passed",
        "unknown_root_cause_rejected",
        "empty_root_cause_rejected",
        "missing_root_cause_rejected",
        "free_text_root_cause_rejected",
        "multiple_classes_rejected",
        "implementation_present",
    )
    if require_success:
        if ok is not True or detail != SUCCESS_DETAIL or any(block.get(key) is not True for key in passed_keys):
            violations.append("failure_attribution")
        elif not samples_match(block.get("samples")):
            violations.append("failure_attribution")
    else:
        if detail not in FAILURE_DETAILS or not isinstance(ok, bool):
            violations.append("failure_attribution")
        elif ok is True and (
            detail != SUCCESS_DETAIL
            or any(block.get(key) is not True for key in passed_keys)
            or not samples_match(block.get("samples"))
        ):
            violations.append("failure_attribution")
        elif ok is not True and (
            any(block.get(key) is not False for key in passed_keys) or block.get("samples") not in ([], None)
        ):
            violations.append("failure_attribution")
    return violations


def _summary(classified: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": True,
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "accepted": classified.get("accepted") is True,
        "terminal_class": classified.get("terminal_class"),
        "rejection": classified.get("rejection"),
        "sample_only": True,
        "classifies_sample_attributions_passed": False,
        "unknown_root_cause_rejected": classified.get("rejection") == "unknown",
        "note": NOTE,
    }
    body.update(_closed_flags())
    return body


def _error_summary(detail: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": False,
        "detail": detail,
        "tool": TOOL,
        "sample_only": True,
        "classifies_sample_attributions_passed": False,
        "unknown_root_cause_rejected": False,
        "note": NOTE,
    }
    body.update(_closed_flags())
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", default=None, help="JSON object or class label to classify")
    parser.add_argument("--samples", action="store_true", help="classify the fixed sample set")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.samples:
        status = stable_scaffold_status()
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return 0 if status.get("ok") is True else 2
    if args.record is None:
        print(json.dumps(_error_summary("record_required"), ensure_ascii=False))
        return 2
    text = args.record.strip()
    if text.startswith("{") or text.startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            print(json.dumps(_error_summary("record_not_json"), ensure_ascii=False))
            return 2
    else:
        payload = text
    classified = classify_record(payload)
    print(json.dumps(_summary(classified), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
