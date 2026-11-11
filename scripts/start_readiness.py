#!/usr/bin/env python3
"""Offline pre-start readiness aggregator and condition-5 claim guard.

Reads the existing sample/offline checkers for founder conditions 1–4 and
classifies sample production reports for condition 5. Sample-pass flags do
not satisfy any founder condition and do not allow can_start_clock.

Condition 5 here is a sample guard only. An honest sample says production
7x24 is NOT_ACCEPTED and a 72h wall, or a 72h-shaped sample, is not
production readiness. A claim of production 7x24 ACCEPTED, PASS, or ready is
refused. A 72h result treated as production readiness is refused. The
Ubuntu-24H wall of 86400.001s is a historical SHORT specimen. Treating that
wall as production readiness is refused. It is not 72h and it is not
production.

This module does not start the 72h clock, does not launch soak_2h.py, and
does not accept production 7x24. Issue #9 comment 6761044915 is not a start.

  python3 scripts/start_readiness.py --samples
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any

TOOL = "scripts/start_readiness.py"
ACTION = "aggregate_sample_checkers"
DUT = "synthetic_sample_readiness"
FOUNDER_CONDITION_ID = "not_production_7x24"
SUCCESS_DETAIL = "implementation_exists_sample_checkers_aggregated"
FAILURE_DETAILS = frozenset(
    {
        SUCCESS_DETAIL,
        "script_missing",
        "aggregation_failed",
        "import_failed",
    }
)
HOLE = "sample_aggregation_is_not_a_start_and_not_production_readiness"
NOTE = (
    "This module aggregates the existing sample/offline checkers for founder conditions 1-4 "
    "and applies a sample guard for condition 5. "
    "aggregates_sample_checkers_passed may be true only for that composition. "
    "rejects_production_claim_from_sample and refuses_72h_as_production_readiness may be true "
    "only for the sample guard. "
    "Those flags do not satisfy any founder condition and do not allow can_start_clock. "
    "A 72h result is not production readiness. "
    "The Ubuntu-24H wall of 86400.001s is a historical SHORT specimen, not 72h and not production. "
    "Issue #9 comment 6761044915 is not a start. "
    "The clock stays NOT STARTED. Production 7x24 stays NOT ACCEPTED."
)
FOUNDER_CONDITION_IDS = (
    "supervision_policy",
    "supervision_cadence_and_supervisor_watchdog",
    "public_evidence",
    "three_way_attribution",
    "not_production_7x24",
)
UBUNTU_24H_WALL_S = 86400.001
UBUNTU_24H_EXPERIMENT = "UBUNTU-24H"
WALL_72H_SECONDS = 259200
SAMPLE_PASS_FLAGS = (
    "classifies_sample_policy_bands_passed",
    "monotonic_sample_sequence_passed",
    "declared_bands_match_founder_policy",
    "writes_on_schedule_passed",
    "dummy_crash_within_10s_passed",
    "classifies_or_validates_sample_public_pack_passed",
    "classifies_sample_attributions_passed",
    "rejects_production_claim_from_sample",
    "refuses_72h_as_production_readiness",
    "aggregates_sample_checkers_passed",
)
CONDITION_KEYS = (
    "condition_1_satisfied",
    "condition_2_satisfied",
    "condition_3_satisfied",
    "condition_4_satisfied",
    "condition_5_satisfied",
)
PROMOTION_KEYS = CONDITION_KEYS + (
    "all_five_conditions_satisfied",
    "sample_passes_satisfy_any_founder_condition",
    "can_start_clock",
    "can_accept_l2_2",
    "can_close_l2_2",
)
SEVENTY_TWO_KEYS = (
    "a_72h_result_is_production_readiness",
    "a_72h_pass_is_production_readiness",
    "seventy_two_hour_is_production_readiness",
)
READINESS_KEYS = SEVENTY_TWO_KEYS + (
    "pass_is_production_readiness",
    "wall_is_production_readiness",
    "ubuntu_24h_short_wall_is_production_readiness",
    "short_wall_is_production_readiness",
    "counts_as_production_readiness",
    "production_readiness",
    "is_production_readiness",
    "counts_as_production_7x24",
)
HONEST_DENIAL_KEYS = SEVENTY_TWO_KEYS + ("wall_is_production_readiness",)
CHECKER_ORDER = (
    "supervision_policy",
    "supervision_cadence",
    "supervisor_watchdog",
    "public_evidence_pack",
    "failure_attribution",
)
CHECKER_PASS_FLAGS = {
    "supervision_policy": (
        "classifies_sample_policy_bands_passed",
        "monotonic_sample_sequence_passed",
        "declared_bands_match_founder_policy",
    ),
    "supervision_cadence": ("writes_on_schedule_passed",),
    "supervisor_watchdog": ("dummy_crash_within_10s_passed",),
    "public_evidence_pack": ("classifies_or_validates_sample_public_pack_passed",),
    "failure_attribution": ("classifies_sample_attributions_passed",),
}
CHECKER_CLOSED_KEYS = (
    "condition_1_satisfied",
    "condition_2_satisfied",
    "condition_3_satisfied",
    "condition_4_satisfied",
    "condition_5_satisfied",
    "committed_constants_satisfy_condition_1",
    "dummy_tests_satisfy_condition_1",
    "implementation_satisfies_condition_1",
    "demonstrates_10_minute_supervision_cadence",
    "is_supervisor_watchdog_of_live_supervisor",
    "dummy_tests_satisfy_condition_2",
    "implementation_satisfies_condition_2",
    "packs_live_soak_evidence",
    "local_only_counts_as_public_evidence",
    "scaffold_sha256sums_is_soak_evidence",
    "dummy_tests_satisfy_condition_3",
    "implementation_satisfies_condition_3",
    "attributes_live_soak_failure",
    "unknown_root_cause_allowed",
    "dummy_tests_satisfy_condition_4",
    "implementation_satisfies_condition_4",
    "can_start_clock",
    "can_accept_l2_2",
    "can_close_l2_2",
    "l2_2_status",
    "clock_state",
    "production_7x24",
    "is_a_start",
    "soak_launched",
)
_CACHE: dict[str, Any] | None = None


def _closed_flags() -> dict[str, Any]:
    return {
        "condition_1_satisfied": False,
        "sample_policy_satisfies_condition_1": False,
        "dummy_tests_satisfy_condition_1": False,
        "implementation_satisfies_condition_1": False,
        "committed_constants_satisfy_condition_1": False,
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
        "condition_3_satisfied": False,
        "sample_pack_satisfies_condition_3": False,
        "dummy_tests_satisfy_condition_3": False,
        "implementation_satisfies_condition_3": False,
        "packs_live_soak_evidence": False,
        "local_only_counts_as_public_evidence": False,
        "scaffold_sha256sums_is_soak_evidence": False,
        "condition_4_satisfied": False,
        "sample_classification_satisfies_condition_4": False,
        "dummy_tests_satisfy_condition_4": False,
        "implementation_satisfies_condition_4": False,
        "attributes_live_soak_failure": False,
        "unknown_root_cause_allowed": False,
        "condition_5_satisfied": False,
        "dummy_tests_satisfy_condition_5": False,
        "implementation_satisfies_condition_5": False,
        "sample_passes_satisfy_any_founder_condition": False,
        "all_five_conditions_satisfied": False,
        "a_72h_result_is_production_readiness": False,
        "a_72h_pass_is_production_readiness": False,
        "ubuntu_24h_short_wall_is_production_readiness": False,
        "ubuntu_24h_counts_as_72h": False,
        "short_wall_is_72h": False,
        "soak_launched": False,
        "documented_soak_argv_executed": False,
        "is_a_start": False,
        "binds_clock_start": False,
        "implies_l2_2_pass": False,
        "implies_l2_2_acceptance": False,
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


def _sample_flags() -> dict[str, Any]:
    closed = _closed_flags()
    keys = (
        "condition_1_satisfied",
        "condition_2_satisfied",
        "condition_3_satisfied",
        "condition_4_satisfied",
        "condition_5_satisfied",
        "dummy_tests_satisfy_condition_5",
        "implementation_satisfies_condition_5",
        "sample_passes_satisfy_any_founder_condition",
        "all_five_conditions_satisfied",
        "a_72h_result_is_production_readiness",
        "a_72h_pass_is_production_readiness",
        "ubuntu_24h_short_wall_is_production_readiness",
        "ubuntu_24h_counts_as_72h",
        "can_start_clock",
        "can_accept_l2_2",
        "can_close_l2_2",
        "l2_2_status",
        "clock_state",
        "production_7x24",
        "is_a_start",
        "soak_launched",
        "demonstrates_10_minute_supervision_cadence",
        "is_supervisor_watchdog_of_live_supervisor",
        "packs_live_soak_evidence",
        "attributes_live_soak_failure",
    )
    flags = {key: closed[key] for key in keys}
    flags["rejects_production_claim_from_sample"] = False
    flags["refuses_72h_as_production_readiness"] = False
    flags["aggregates_sample_checkers_passed"] = False
    return flags


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ").replace("×", "x")
    return " ".join(text.split())


def _token_key(value: Any) -> str:
    return "_".join(_norm(value).split())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-6)


def _decision(accepted: bool, rejection: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "accepted": accepted is True,
        "rejection": None if accepted is True else rejection,
        "sample_only": True,
        "offline": True,
    }
    body.update(_closed_flags())
    body["rejects_production_claim_from_sample"] = False
    body["refuses_72h_as_production_readiness"] = False
    body["aggregates_sample_checkers_passed"] = False
    return body


def _production_token(report: dict[str, Any]) -> str:
    raw = report.get("production_7x24", report.get("claimed_production_7x24"))
    if isinstance(raw, dict):
        raw = raw.get("claimed", raw.get("status"))
    if raw is None and isinstance(report.get("production"), dict):
        nested = report["production"]
        raw = nested.get("claimed", nested.get("production_7x24"))
        if nested.get("pass_is_production_readiness") is True and raw is None:
            raw = "ready"
    if raw is None:
        raw = report.get("production") if not isinstance(report.get("production"), dict) else None
    if raw is None:
        return ""
    return _token_key(raw)


def _is_production_claim_token(token: str) -> bool:
    if not token or token in {"not_accepted", "not_ready", "unaccepted"}:
        return False
    if token.startswith("not_") or "_not_" in token:
        return False
    if token in {"accepted", "pass", "ready", "production_accepted", "production_ready"}:
        return True
    return token.endswith("_accepted") or token.endswith("_pass") or token.endswith("_ready")


def _explicit_composition(report: dict[str, Any]) -> str:
    raw = report.get("composition", report.get("combine", report.get("reducer")))
    token = _token_key(raw)
    if token in {"or", "any", "disjunction"}:
        return "or"
    if token in {"and", "all", "conjunction"}:
        return "and"
    return ""


def _flag_true(report: dict[str, Any], key: str) -> bool:
    return report.get(key) is True


def _any_sample_pass_true(report: dict[str, Any]) -> bool:
    return any(_flag_true(report, key) for key in SAMPLE_PASS_FLAGS)


def _target_open(report: dict[str, Any]) -> bool:
    for key in PROMOTION_KEYS:
        value = report.get(key)
        if value is True:
            return True
        if isinstance(value, str) and _token_key(value) in {_token_key(flag) for flag in SAMPLE_PASS_FLAGS}:
            return True
    return False


def promotes_sample_passes(report: dict[str, Any]) -> bool:
    """True when sample-pass flags are copied into a condition or into can_start_clock."""
    if not isinstance(report, dict):
        return False
    mode = _explicit_composition(report)
    if mode in {"or", "and"} and _target_open(report):
        return True
    if _any_sample_pass_true(report) and _target_open(report):
        return True
    return False


def _is_ubuntu_short(report: dict[str, Any], wall: float | None) -> bool:
    if wall is not None and _close(wall, UBUNTU_24H_WALL_S):
        return True
    experiment = _token_key(report.get("experiment") or report.get("specimen") or "")
    role = _token_key(report.get("role") or report.get("specimen_role") or "")
    if experiment in {"ubuntu_24h", "ubuntu24h"}:
        return True
    return role == "historical_short_specimen"


def _is_72h_shaped(report: dict[str, Any], wall: float | None) -> bool:
    if report.get("shaped_as_72h") is True:
        return True
    if wall is not None and _close(wall, WALL_72H_SECONDS):
        return True
    role = _token_key(report.get("wall_role") or "")
    return role in {"72h", "sample_72h", "sample_72h_not_production", "seventy_two_hour"}


def _readiness_true(report: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(report.get(key) is True for key in keys)


def _wall(report: dict[str, Any]) -> float | None:
    for key in ("wall_seconds", "wall_elapsed_s", "elapsed_seconds"):
        if key in report:
            return _number(report.get(key))
    return None


def _says_pass_or_start(report: dict[str, Any]) -> bool:
    status = _token_key(report.get("l2_2_status"))
    clock = _token_key(report.get("clock_state"))
    if status in {"pass", "accepted", "started"} or status.startswith("pass"):
        return True
    if clock in {"started", "wall_observed"}:
        return True
    return (
        report.get("can_start_clock") is True
        or report.get("is_a_start") is True
        or report.get("can_accept_l2_2") is True
        or report.get("can_close_l2_2") is True
    )


def _honest_sample(report: dict[str, Any], token: str) -> bool:
    if token != "not_accepted":
        return False
    if report.get("sample_only") is not True and report.get("offline") is not True:
        return False
    if not any(report.get(key) is False for key in HONEST_DENIAL_KEYS):
        return False
    if _readiness_true(report, READINESS_KEYS):
        return False
    if report.get("condition_5_satisfied") is True or report.get("all_five_conditions_satisfied") is True:
        return False
    if report.get("dummy_tests_satisfy_condition_5") is True or report.get("implementation_satisfies_condition_5") is True:
        return False
    if _says_pass_or_start(report):
        return False
    return True


def assess_report(report: Any) -> dict[str, Any]:
    """Classify one sample production report. Does not satisfy condition 5."""
    if not isinstance(report, dict):
        return _decision(False, "missing")
    if promotes_sample_passes(report):
        return _decision(False, "sample_passes_promoted")
    wall = _wall(report)
    ubuntu = _is_ubuntu_short(report, wall)
    shaped = _is_72h_shaped(report, wall)
    token = _production_token(report)
    claim = _is_production_claim_token(token)
    seventy_two = _readiness_true(report, SEVENTY_TWO_KEYS)
    readiness = _readiness_true(report, READINESS_KEYS)
    if ubuntu and (readiness or claim):
        return _decision(False, "short_wall_as_production_readiness")
    if seventy_two or (shaped and (readiness or claim)):
        return _decision(False, "72h_as_production_readiness")
    if claim:
        return _decision(False, "production_claim")
    if (
        report.get("condition_5_satisfied") is True
        or report.get("all_five_conditions_satisfied") is True
        or report.get("sample_passes_satisfy_any_founder_condition") is True
        or report.get("dummy_tests_satisfy_condition_5") is True
        or report.get("implementation_satisfies_condition_5") is True
    ):
        return _decision(False, "condition_5_claimed")
    if _says_pass_or_start(report):
        return _decision(False, "clock_or_status_claim")
    if _honest_sample(report, token):
        return _decision(True, None)
    return _decision(False, "not_an_honest_sample")


def _pass_map(source: dict[str, bool]) -> dict[str, bool]:
    return {key: source.get(key) is True for key in SAMPLE_PASS_FLAGS if key != "aggregates_sample_checkers_passed"}


def forbidden_composition(passes: dict[str, bool], mode: str) -> dict[str, Any]:
    """Build the lie that ORs or ANDs sample-pass flags into founder conditions.

    The returned object is an input to assess_report. It is not a status.
    """
    flags = _pass_map(passes)
    if mode == "and":
        combined = all(flags.values()) if flags else False
        conditions = {key: combined for key in CONDITION_KEYS}
        any_condition = combined
        all_five = combined
        clock = combined
    else:
        conditions = {
            "condition_1_satisfied": (
                flags["classifies_sample_policy_bands_passed"]
                or flags["monotonic_sample_sequence_passed"]
                or flags["declared_bands_match_founder_policy"]
            ),
            "condition_2_satisfied": flags["writes_on_schedule_passed"] or flags["dummy_crash_within_10s_passed"],
            "condition_3_satisfied": flags["classifies_or_validates_sample_public_pack_passed"],
            "condition_4_satisfied": flags["classifies_sample_attributions_passed"],
            "condition_5_satisfied": (
                flags["rejects_production_claim_from_sample"] or flags["refuses_72h_as_production_readiness"]
            ),
        }
        any_condition = any(conditions.values())
        all_five = any_condition
        clock = any_condition
    body: dict[str, Any] = {
        "composition": "and" if mode == "and" else "or",
        "sample_only": True,
        "offline": True,
        "production_7x24": "NOT_ACCEPTED",
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
    }
    body.update(flags)
    body.update(conditions)
    body["all_five_conditions_satisfied"] = all_five
    body["sample_passes_satisfy_any_founder_condition"] = any_condition
    body["can_start_clock"] = clock
    return body


SAMPLE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "honest_not_accepted",
        "report": {
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "wall_seconds": WALL_72H_SECONDS,
            "wall_role": "sample_72h_not_production",
            "a_72h_result_is_production_readiness": False,
            "a_72h_pass_is_production_readiness": False,
            "ubuntu_24h_short_wall_is_production_readiness": False,
        },
        "accepted": True,
        "rejection": None,
    },
    {
        "id": "honest_72h_shaped_sample",
        "report": {
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "shaped_as_72h": True,
            "a_72h_result_is_production_readiness": False,
            "a_72h_pass_is_production_readiness": False,
        },
        "accepted": True,
        "rejection": None,
    },
    {
        "id": "honest_ubuntu_short_is_not_production",
        "report": {
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "wall_seconds": UBUNTU_24H_WALL_S,
            "experiment": UBUNTU_24H_EXPERIMENT,
            "role": "historical_short_specimen",
            "a_72h_result_is_production_readiness": False,
            "ubuntu_24h_short_wall_is_production_readiness": False,
            "ubuntu_24h_counts_as_72h": False,
        },
        "accepted": True,
        "rejection": None,
    },
    {
        "id": "production_accepted",
        "report": {
            "sample_only": True,
            "offline": True,
            "production_7x24": "ACCEPTED",
            "a_72h_result_is_production_readiness": False,
        },
        "accepted": False,
        "rejection": "production_claim",
    },
    {
        "id": "production_pass",
        "report": {"sample_only": True, "offline": True, "production_7x24": "PASS"},
        "accepted": False,
        "rejection": "production_claim",
    },
    {
        "id": "production_ready",
        "report": {"sample_only": True, "offline": True, "production_7x24": "ready"},
        "accepted": False,
        "rejection": "production_claim",
    },
    {
        "id": "seventy_two_hour_called_readiness",
        "report": {
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "wall_seconds": WALL_72H_SECONDS,
            "a_72h_result_is_production_readiness": True,
        },
        "accepted": False,
        "rejection": "72h_as_production_readiness",
    },
    {
        "id": "ubuntu_short_called_readiness",
        "report": {
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "wall_seconds": UBUNTU_24H_WALL_S,
            "experiment": UBUNTU_24H_EXPERIMENT,
            "role": "historical_short_specimen",
            "ubuntu_24h_short_wall_is_production_readiness": True,
            "a_72h_result_is_production_readiness": False,
        },
        "accepted": False,
        "rejection": "short_wall_as_production_readiness",
    },
    {
        "id": "condition_5_called_satisfied",
        "report": {
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "a_72h_result_is_production_readiness": False,
            "condition_5_satisfied": True,
            "dummy_tests_satisfy_condition_5": True,
            "implementation_satisfies_condition_5": True,
        },
        "accepted": False,
        "rejection": "condition_5_claimed",
    },
    {
        "id": "or_sample_passes_into_conditions",
        "report": {
            "composition": "or",
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "classifies_sample_policy_bands_passed": True,
            "condition_1_satisfied": True,
            "can_start_clock": True,
            "a_72h_result_is_production_readiness": False,
        },
        "accepted": False,
        "rejection": "sample_passes_promoted",
    },
    {
        "id": "and_sample_passes_into_can_start_clock",
        "report": {
            "composition": "and",
            "sample_only": True,
            "offline": True,
            "production_7x24": "NOT_ACCEPTED",
            "classifies_sample_policy_bands_passed": True,
            "writes_on_schedule_passed": True,
            "dummy_crash_within_10s_passed": True,
            "classifies_or_validates_sample_public_pack_passed": True,
            "classifies_sample_attributions_passed": True,
            "rejects_production_claim_from_sample": True,
            "refuses_72h_as_production_readiness": True,
            "condition_1_satisfied": True,
            "condition_2_satisfied": True,
            "condition_3_satisfied": True,
            "condition_4_satisfied": True,
            "condition_5_satisfied": True,
            "all_five_conditions_satisfied": True,
            "sample_passes_satisfy_any_founder_condition": True,
            "can_start_clock": True,
        },
        "accepted": False,
        "rejection": "sample_passes_promoted",
    },
)


def _sample_row(spec: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": spec["id"],
        "accepted": decision.get("accepted") is True,
        "rejection": decision.get("rejection"),
        "sample_only": True,
        "offline": True,
    }
    row.update(_sample_flags())
    return row


def canonical_samples() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in SAMPLE_SPECS:
        rows.append(_sample_row(spec, assess_report(spec["report"])))
    return rows


def samples_match(rows: Any) -> bool:
    if not isinstance(rows, list) or len(rows) != len(SAMPLE_SPECS):
        return False
    expected = canonical_samples()
    for got, want in zip(rows, expected):
        if not isinstance(got, dict):
            return False
        for key, value in want.items():
            if got.get(key) != value:
                return False
    return True


def _guard_result(rows: list[dict[str, Any]]) -> dict[str, bool]:
    by_id = {row["id"]: row for row in rows}
    production_ids = ("production_accepted", "production_pass", "production_ready")
    rejects = all(by_id[item]["accepted"] is False and by_id[item]["rejection"] == "production_claim" for item in production_ids)
    refuses = (
        by_id["seventy_two_hour_called_readiness"]["accepted"] is False
        and by_id["seventy_two_hour_called_readiness"]["rejection"] == "72h_as_production_readiness"
        and by_id["ubuntu_short_called_readiness"]["accepted"] is False
        and by_id["ubuntu_short_called_readiness"]["rejection"] == "short_wall_as_production_readiness"
        and by_id["honest_not_accepted"]["accepted"] is True
        and by_id["honest_72h_shaped_sample"]["accepted"] is True
        and by_id["honest_ubuntu_short_is_not_production"]["accepted"] is True
    )
    promoted = (
        by_id["or_sample_passes_into_conditions"]["rejection"] == "sample_passes_promoted"
        and by_id["and_sample_passes_into_can_start_clock"]["rejection"] == "sample_passes_promoted"
        and by_id["condition_5_called_satisfied"]["rejection"] == "condition_5_claimed"
    )
    closed = all(row.get("condition_5_satisfied") is False and row.get("can_start_clock") is False for row in rows)
    return {
        "rejects_production_claim_from_sample": rejects and promoted and closed,
        "refuses_72h_as_production_readiness": refuses and promoted and closed,
        "samples_ok": rejects and refuses and promoted and closed,
    }


def _expected_closed(key: str) -> Any:
    if key in {"l2_2_status", "clock_state"}:
        return "NOT_STARTED"
    if key == "production_7x24":
        return "NOT_ACCEPTED"
    return False


def _checker_slice(name: str, block: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "tool": block.get("tool"),
        "ok": block.get("ok") is True,
        "detail": block.get("detail"),
    }
    for flag in CHECKER_PASS_FLAGS[name]:
        row[flag] = block.get(flag) is True
    for key in CHECKER_CLOSED_KEYS:
        if key in block:
            row[key] = block.get(key)
    return row


def _slice_honest(name: str, row: dict[str, Any]) -> bool:
    if row.get("ok") is not True:
        return False
    if any(row.get(flag) is not True for flag in CHECKER_PASS_FLAGS[name]):
        return False
    for key, value in row.items():
        if key in {"tool", "ok", "detail"} or key in CHECKER_PASS_FLAGS[name]:
            continue
        if value != _expected_closed(key):
            return False
    return True


def _load_checker_modules() -> dict[str, Any] | None:
    try:
        import failure_attribution as attribution
        import public_evidence_pack as evidence_pack
        import supervision_cadence as cadence
        import supervision_policy as policy
        import supervisor_watchdog as watchdog
    except Exception:
        return None
    return {
        "supervision_policy": policy,
        "supervision_cadence": cadence,
        "supervisor_watchdog": watchdog,
        "public_evidence_pack": evidence_pack,
        "failure_attribution": attribution,
    }


def read_checkers() -> dict[str, Any] | None:
    """Invoke the four sample checkers. None when one of them cannot be imported."""
    modules = _load_checker_modules()
    if modules is None:
        return None
    blocks: dict[str, Any] = {}
    for name, module in modules.items():
        status = module.stable_scaffold_status()
        if module.scaffold_violations(status, require_success=True):
            blocks[name] = status
            blocks["_violations"] = name
            return blocks
        blocks[name] = status
    return blocks


def _checker_rows(blocks: dict[str, Any]) -> dict[str, Any]:
    return {name: _checker_slice(name, blocks[name]) for name in CHECKER_ORDER if isinstance(blocks.get(name), dict)}


def _passes_from_rows(rows: dict[str, Any], guard: dict[str, bool]) -> dict[str, bool]:
    passes = {key: False for key in SAMPLE_PASS_FLAGS if key != "aggregates_sample_checkers_passed"}
    for name, flags in CHECKER_PASS_FLAGS.items():
        row = rows.get(name) if isinstance(rows.get(name), dict) else {}
        for flag in flags:
            passes[flag] = row.get(flag) is True
    passes["rejects_production_claim_from_sample"] = guard.get("rejects_production_claim_from_sample") is True
    passes["refuses_72h_as_production_readiness"] = guard.get("refuses_72h_as_production_readiness") is True
    return passes


def _composition_row(mode: str, forbidden: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "or_of_sample_passes" if mode == "or" else "and_of_sample_passes",
        "composition": mode,
        "accepted": decision.get("accepted") is True,
        "rejection": decision.get("rejection"),
        "promoted_condition_1": forbidden.get("condition_1_satisfied") is True,
        "promoted_condition_2": forbidden.get("condition_2_satisfied") is True,
        "promoted_condition_3": forbidden.get("condition_3_satisfied") is True,
        "promoted_condition_4": forbidden.get("condition_4_satisfied") is True,
        "promoted_condition_5": forbidden.get("condition_5_satisfied") is True,
        "promoted_all_five": forbidden.get("all_five_conditions_satisfied") is True,
        "promoted_any_founder_condition": forbidden.get("sample_passes_satisfy_any_founder_condition") is True,
        "promoted_can_start_clock": forbidden.get("can_start_clock") is True,
        "sample_only": True,
        "offline": True,
    }
    row.update(_sample_flags())
    return row


def _composition_refused(row: dict[str, Any]) -> bool:
    promoted = (
        "promoted_condition_1",
        "promoted_condition_2",
        "promoted_condition_3",
        "promoted_condition_4",
        "promoted_condition_5",
        "promoted_all_five",
        "promoted_any_founder_condition",
        "promoted_can_start_clock",
    )
    return (
        row.get("accepted") is False
        and row.get("rejection") == "sample_passes_promoted"
        and all(row.get(key) is True for key in promoted)
        and row.get("condition_1_satisfied") is False
        and row.get("condition_5_satisfied") is False
        and row.get("all_five_conditions_satisfied") is False
        and row.get("sample_passes_satisfy_any_founder_condition") is False
        and row.get("can_start_clock") is False
        and row.get("aggregates_sample_checkers_passed") is False
    )


def run_offline_exercise() -> dict[str, Any]:
    """Compose the sample checkers and the condition-5 guard. Not a start."""
    blocks = read_checkers()
    if blocks is None:
        return {"ok": False, "detail": "import_failed"}
    if blocks.get("_violations"):
        return {"ok": False, "detail": "aggregation_failed"}
    rows = canonical_samples()
    if not samples_match(rows):
        return {"ok": False, "detail": "aggregation_failed"}
    expected = {spec["id"]: spec for spec in SAMPLE_SPECS}
    if any(
        rows[index]["accepted"] is not expected[rows[index]["id"]]["accepted"]
        or rows[index]["rejection"] != expected[rows[index]["id"]]["rejection"]
        for index in range(len(rows))
    ):
        return {"ok": False, "detail": "aggregation_failed"}
    guard = _guard_result(rows)
    checker_rows = _checker_rows(blocks)
    if any(not _slice_honest(name, checker_rows[name]) for name in CHECKER_ORDER):
        return {"ok": False, "detail": "aggregation_failed"}
    passes = _passes_from_rows(checker_rows, guard)
    if not all(passes.values()):
        return {"ok": False, "detail": "aggregation_failed"}
    compositions: list[dict[str, Any]] = []
    for mode in ("or", "and"):
        forbidden = forbidden_composition(passes, mode)
        decision = assess_report(forbidden)
        compositions.append(_composition_row(mode, forbidden, decision))
    if any(not _composition_refused(row) for row in compositions):
        return {"ok": False, "detail": "aggregation_failed"}
    if not guard["samples_ok"]:
        return {"ok": False, "detail": "aggregation_failed"}
    return {
        "ok": True,
        "detail": SUCCESS_DETAIL,
        "aggregates_sample_checkers_passed": True,
        "rejects_production_claim_from_sample": True,
        "refuses_72h_as_production_readiness": True,
        "or_composition_refused": True,
        "and_composition_refused": True,
        "samples": rows,
        "compositions": compositions,
        "checkers": checker_rows,
        "sample_pass_flags": passes,
    }


def _refused_claims() -> list[dict[str, Any]]:
    common = _closed_flags()
    specs = (
        ("production_accepted_called_ready", "production_claim_from_sample"),
        ("72h_called_production_readiness", "seventy_two_hour_called_production_readiness"),
        ("ubuntu_24h_short_called_production_readiness", "short_wall_called_production_readiness"),
        ("or_sample_passes_called_conditions", "sample_passes_or_into_condition"),
        ("and_sample_passes_called_can_start_clock", "sample_passes_and_into_clock"),
    )
    rows: list[dict[str, Any]] = []
    for label, flag in specs:
        row: dict[str, Any] = {
            "label": label,
            flag: True,
            "condition_5_claimed": False,
            "pass_or_start_claimed": False,
        }
        row.update(common)
        rows.append(row)
    return rows


def _scaffold_shell(
    detail: str,
    *,
    ok: bool,
    implementation_present: bool,
    measured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if detail not in FAILURE_DETAILS:
        detail = "aggregation_failed"
    passed = ok is True and detail == SUCCESS_DETAIL and isinstance(measured, dict)
    block: dict[str, Any] = {
        "ok": passed,
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "detail": detail,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "founder_condition_ids": list(FOUNDER_CONDITION_IDS),
        "implementation_present": implementation_present and passed,
        "sample_only": True,
        "offline": True,
        "aggregates_sample_checkers_passed": passed,
        "rejects_production_claim_from_sample": passed,
        "refuses_72h_as_production_readiness": passed,
        "or_composition_refused": passed,
        "and_composition_refused": passed,
        "ubuntu_24h_wall_seconds": UBUNTU_24H_WALL_S,
        "wall_72h_seconds": WALL_72H_SECONDS,
        "samples": measured.get("samples") if passed else [],
        "compositions": measured.get("compositions") if passed else [],
        "checkers": measured.get("checkers") if passed else {},
        "sample_pass_flags": measured.get("sample_pass_flags") if passed else {},
        "hole": HOLE,
        "note": NOTE,
        "production_claim_from_sample": False,
        "seventy_two_hour_called_production_readiness": False,
        "short_wall_called_production_readiness": False,
        "sample_passes_or_into_condition": False,
        "sample_passes_and_into_clock": False,
        "condition_5_claimed": False,
        "pass_or_start_claimed": False,
        "refused_claims": _refused_claims(),
    }
    block.update(_closed_flags())
    return block


def scaffold_status_for_root(script_present: bool) -> dict[str, Any]:
    """Skip the aggregate when the inspected root has no module."""
    if not script_present:
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    return stable_scaffold_status()


def stable_scaffold_status(*, force: bool = False) -> dict[str, Any]:
    """Deterministic sample aggregate. No soak and no clock start."""
    global _CACHE
    if _CACHE is not None and not force:
        return json.loads(json.dumps(_CACHE))
    measured = run_offline_exercise()
    if measured.get("ok") is True and measured.get("detail") == SUCCESS_DETAIL:
        block = _scaffold_shell(SUCCESS_DETAIL, ok=True, implementation_present=True, measured=measured)
        _CACHE = json.loads(json.dumps(block))
        return json.loads(json.dumps(block))
    detail = measured.get("detail") if measured.get("detail") in FAILURE_DETAILS else "aggregation_failed"
    return _scaffold_shell(str(detail), ok=False, implementation_present=False)


def _claim_promotion_mode(claim: dict[str, Any]) -> str:
    explicit = _explicit_composition(claim)
    if explicit:
        return explicit
    if claim.get("can_start_clock") is True and promotes_sample_passes(claim):
        present = [flag for flag in SAMPLE_PASS_FLAGS if flag in claim]
        if len(present) >= 2 and all(claim.get(flag) is True for flag in present):
            if all(claim.get(key) is True for key in CONDITION_KEYS):
                return "and"
        return "or"
    if promotes_sample_passes(claim):
        return "or"
    return ""


def annotate_scaffold_claim(block: dict[str, Any], claim: dict[str, Any] | None) -> None:
    """Record a pretense. Closed flags are applied again by the caller."""
    block["production_claim_from_sample"] = False
    block["seventy_two_hour_called_production_readiness"] = False
    block["short_wall_called_production_readiness"] = False
    block["sample_passes_or_into_condition"] = False
    block["sample_passes_and_into_clock"] = False
    block["condition_5_claimed"] = False
    block["pass_or_start_claimed"] = False
    if not isinstance(claim, dict):
        return
    decision = assess_report(claim)
    rejection = decision.get("rejection")
    if rejection == "production_claim" or _is_production_claim_token(_production_token(claim)):
        block["production_claim_from_sample"] = True
    if rejection == "72h_as_production_readiness" or _readiness_true(claim, SEVENTY_TWO_KEYS):
        block["seventy_two_hour_called_production_readiness"] = True
    if rejection == "short_wall_as_production_readiness" or claim.get("ubuntu_24h_short_wall_is_production_readiness") is True:
        block["short_wall_called_production_readiness"] = True
    mode = _claim_promotion_mode(claim)
    if rejection == "sample_passes_promoted" or mode:
        if mode == "and":
            block["sample_passes_and_into_clock"] = True
            block["sample_passes_or_into_condition"] = True
        else:
            block["sample_passes_or_into_condition"] = True
            if claim.get("can_start_clock") is True:
                block["sample_passes_and_into_clock"] = True
    if rejection == "condition_5_claimed" or any(
        claim.get(key) is True
        for key in (
            "condition_5_satisfied",
            "dummy_tests_satisfy_condition_5",
            "implementation_satisfies_condition_5",
            "all_five_conditions_satisfied",
            "sample_passes_satisfy_any_founder_condition",
        )
    ):
        block["condition_5_claimed"] = True
    if any(claim.get(key) is True for key in CONDITION_KEYS[:4]):
        block["sample_passes_or_into_condition"] = True
        block["condition_5_claimed"] = True
    if _says_pass_or_start(claim) or rejection == "clock_or_status_claim":
        block["pass_or_start_claimed"] = True


def _flag_violation(key: str) -> str:
    if key in {
        "condition_1_satisfied",
        "sample_policy_satisfies_condition_1",
        "dummy_tests_satisfy_condition_1",
        "implementation_satisfies_condition_1",
        "committed_constants_satisfy_condition_1",
    }:
        return "condition_1_unsatisfied"
    if key in {
        "condition_2_satisfied",
        "offline_exercise_satisfies_condition_2",
        "time_compressed_exercise_satisfies_condition_2",
        "demonstrates_10_minute_supervision_cadence",
        "dummy_tests_satisfy_condition_2",
        "scaffold_satisfies_condition_2",
        "implementation_satisfies_condition_2",
        "is_supervisor_watchdog_of_live_supervisor",
        "is_live_l2_2_supervisor",
        "is_live_l2_2_supervisor_watchdog",
    }:
        return "condition_2_unsatisfied"
    if key in {
        "condition_3_satisfied",
        "sample_pack_satisfies_condition_3",
        "dummy_tests_satisfy_condition_3",
        "implementation_satisfies_condition_3",
        "packs_live_soak_evidence",
        "local_only_counts_as_public_evidence",
        "scaffold_sha256sums_is_soak_evidence",
    }:
        return "condition_3_unsatisfied"
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
        "condition_5_satisfied",
        "dummy_tests_satisfy_condition_5",
        "implementation_satisfies_condition_5",
        "all_five_conditions_satisfied",
    }:
        return "condition_5_unsatisfied"
    if key == "sample_passes_satisfy_any_founder_condition":
        return "sample_passes_do_not_satisfy_conditions"
    if key in {
        "a_72h_result_is_production_readiness",
        "a_72h_pass_is_production_readiness",
        "ubuntu_24h_short_wall_is_production_readiness",
        "ubuntu_24h_counts_as_72h",
        "short_wall_is_72h",
        "production_7x24",
        "implies_l2_2_acceptance",
    }:
        return "production_claim"
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
    if key in {"clock_state", "clock_effect"}:
        return "clock_state"
    if key in {"soak_launched", "documented_soak_argv_executed"}:
        return "soak_launched"
    return "start_readiness"


def _compositions_match(rows: Any, passes: Any) -> bool:
    if not isinstance(rows, list) or len(rows) != 2 or not isinstance(passes, dict):
        return False
    expected: list[dict[str, Any]] = []
    for mode in ("or", "and"):
        forbidden = forbidden_composition(passes, mode)
        expected.append(_composition_row(mode, forbidden, assess_report(forbidden)))
    for got, want in zip(rows, expected):
        if not isinstance(got, dict):
            return False
        for key, value in want.items():
            if got.get(key) != value:
                return False
        if not _composition_refused(got):
            return False
    return True


def scaffold_violations(block: Any, *, require_success: bool = True) -> list[str]:
    """Reject a report that treats sample passes as a founder condition or a start."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["start_readiness"]
    for key, expected in _closed_flags().items():
        if block.get(key) != expected:
            violations.append(_flag_violation(key))
    constants = {
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "founder_condition_ids": list(FOUNDER_CONDITION_IDS),
        "hole": HOLE,
        "note": NOTE,
        "sample_only": True,
        "offline": True,
        "ubuntu_24h_wall_seconds": UBUNTU_24H_WALL_S,
        "wall_72h_seconds": WALL_72H_SECONDS,
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            violations.append("start_readiness")
    for key in (
        "production_claim_from_sample",
        "seventy_two_hour_called_production_readiness",
        "short_wall_called_production_readiness",
        "sample_passes_or_into_condition",
        "sample_passes_and_into_clock",
        "condition_5_claimed",
        "pass_or_start_claimed",
    ):
        if not isinstance(block.get(key), bool):
            violations.append("start_readiness")
    claims = block.get("refused_claims")
    expected_labels = [
        "production_accepted_called_ready",
        "72h_called_production_readiness",
        "ubuntu_24h_short_called_production_readiness",
        "or_sample_passes_called_conditions",
        "and_sample_passes_called_can_start_clock",
    ]
    flags = (
        "production_claim_from_sample",
        "seventy_two_hour_called_production_readiness",
        "short_wall_called_production_readiness",
        "sample_passes_or_into_condition",
        "sample_passes_and_into_clock",
    )
    if not isinstance(claims, list):
        violations.append("start_readiness")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if labels != expected_labels:
            violations.append("start_readiness")
        else:
            for item, flag in zip(claims, flags):
                if item.get(flag) is not True or item.get("condition_5_satisfied") is not False:
                    violations.append("condition_5_unsatisfied")
                if item.get("all_five_conditions_satisfied") is not False:
                    violations.append("condition_5_unsatisfied")
                if item.get("sample_passes_satisfy_any_founder_condition") is not False:
                    violations.append("sample_passes_do_not_satisfy_conditions")
                if item.get("l2_2_status") != "NOT_STARTED" or item.get("can_start_clock") is not False:
                    violations.append("offline_probe_is_not_a_start")
                if item.get("production_7x24") != "NOT_ACCEPTED":
                    violations.append("production_claim")
    earned = (
        "aggregates_sample_checkers_passed",
        "rejects_production_claim_from_sample",
        "refuses_72h_as_production_readiness",
        "or_composition_refused",
        "and_composition_refused",
        "implementation_present",
    )
    detail = block.get("detail")
    ok = block.get("ok")
    if require_success:
        if ok is not True or detail != SUCCESS_DETAIL or any(block.get(key) is not True for key in earned):
            violations.append("start_readiness")
        elif not samples_match(block.get("samples")) or not _compositions_match(
            block.get("compositions"), block.get("sample_pass_flags")
        ):
            violations.append("start_readiness")
        else:
            live = read_checkers()
            checkers = block.get("checkers")
            if live is None or not isinstance(checkers, dict):
                violations.append("start_readiness")
            else:
                expected_rows = _checker_rows(live)
                if checkers != expected_rows or any(not _slice_honest(name, checkers.get(name)) for name in CHECKER_ORDER):
                    violations.append("start_readiness")
    else:
        if detail not in FAILURE_DETAILS or not isinstance(ok, bool):
            violations.append("start_readiness")
        elif ok is True and (
            detail != SUCCESS_DETAIL
            or any(block.get(key) is not True for key in earned)
            or not samples_match(block.get("samples"))
            or not _compositions_match(block.get("compositions"), block.get("sample_pass_flags"))
        ):
            violations.append("start_readiness")
        elif ok is not True and (
            any(block.get(key) is not False for key in earned)
            or block.get("samples") not in ([], None)
            or block.get("compositions") not in ([], None)
            or block.get("checkers") not in ({}, None)
        ):
            violations.append("start_readiness")
    return violations


def _summary(decision: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": True,
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "accepted": decision.get("accepted") is True,
        "rejection": decision.get("rejection"),
        "sample_only": True,
        "offline": True,
        "aggregates_sample_checkers_passed": False,
        "rejects_production_claim_from_sample": False,
        "refuses_72h_as_production_readiness": False,
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
        "offline": True,
        "aggregates_sample_checkers_passed": False,
        "rejects_production_claim_from_sample": False,
        "refuses_72h_as_production_readiness": False,
        "note": NOTE,
    }
    body.update(_closed_flags())
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default=None, help="JSON object to classify as a sample production report")
    parser.add_argument("--samples", action="store_true", help="aggregate the sample checkers and the condition-5 guard")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.samples:
        status = stable_scaffold_status()
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return 0 if status.get("ok") is True else 2
    if args.report is None:
        print(json.dumps(_error_summary("report_required"), ensure_ascii=False))
        return 2
    text = args.report.strip()
    if not (text.startswith("{") or text.startswith("[")):
        print(json.dumps(_error_summary("report_not_json"), ensure_ascii=False))
        return 2
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        print(json.dumps(_error_summary("report_not_json"), ensure_ascii=False))
        return 2
    print(json.dumps(_summary(assess_report(payload)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
