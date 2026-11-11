#!/usr/bin/env python3
"""Sample supervision-policy check for founder condition 1.

Offline only. Confirms the committed gap bands in scripts/coverage_gap_log.py
match the founder rule, classifies sample gaps through classify_band, and
checks sample timestamp / mono_seconds sequences for a backward jump.

Founder rule: yellow from 13s through 300s inclusive, red strictly above 300s,
and a monotonic clock. A wall clock that goes backwards is not monotonic.
A policy that starts yellow at a different second, or that treats 300s as red,
is refused.

Matching those committed constants does not satisfy founder condition 1, does
not declare the pre-start policy gate, and does not start the clock.

  python3 scripts/supervision_policy.py --samples
"""
from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
from pathlib import Path
from typing import Any

import coverage_gap_log as gaplog

TOOL = "scripts/supervision_policy.py"
ACTION = "classify_sample_policy"
DUT = "synthetic_sample_policy"
GAP_LOGGER = "scripts/coverage_gap_log.py"
MONITOR = "scripts/supervision_monitor.py"
FOUNDER_CONDITION_ID = "supervision_policy"
SUCCESS_DETAIL = "implementation_exists_sample_policy_classified"
FAILURE_DETAILS = frozenset(
    {
        SUCCESS_DETAIL,
        "script_missing",
        "classification_failed",
        "import_failed",
    }
)
HOLE = "sample_policy_check_is_not_the_pre_start_gate"
NOTE = (
    "This module checks sample supervision-policy bands and sample monotonic sequences only. "
    "Yellow is 13s through 300s inclusive. Red is strictly above 300s. "
    "Sample gaps are classified by scripts/coverage_gap_log.classify_band. "
    "A backward timestamp or mono_seconds jump is rejected. A wall clock that goes backwards is not monotonic. "
    "A policy with different bands, including yellow starting at 10s or red at 300s inclusive, is refused. "
    "scripts/supervision_monitor.py records mono_seconds with time.monotonic(); this check does not run that loop. "
    "Matching the committed 13/300 constants does not satisfy founder condition 1 and does not start L2-2."
)
FOUNDER_YELLOW_MIN_SECONDS = 13.0
FOUNDER_YELLOW_MAX_SECONDS = 300.0
FOUNDER_RED_EXCLUSIVE_MIN_SECONDS = 300.0
JUST_ABOVE_RED_SECONDS = math.nextafter(FOUNDER_RED_EXCLUSIVE_MIN_SECONDS, math.inf)
ROOT_NOTE_CLOCK = "monotonic"
_CACHE: dict[str, Any] | None = None


def _closed_flags() -> dict[str, Any]:
    return {
        "condition_1_satisfied": False,
        "sample_policy_satisfies_condition_1": False,
        "dummy_tests_satisfy_condition_1": False,
        "implementation_satisfies_condition_1": False,
        "committed_constants_satisfy_condition_1": False,
        "alternate_bands_accepted": False,
        "backward_clock_is_monotonic": False,
        "watches_live_soak": False,
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


def _sample_flags() -> dict[str, Any]:
    closed = _closed_flags()
    keys = (
        "condition_1_satisfied",
        "sample_policy_satisfies_condition_1",
        "dummy_tests_satisfy_condition_1",
        "implementation_satisfies_condition_1",
        "committed_constants_satisfy_condition_1",
        "alternate_bands_accepted",
        "backward_clock_is_monotonic",
        "watches_live_soak",
        "condition_2_satisfied",
        "condition_3_satisfied",
        "condition_4_satisfied",
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


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def _token_key(value: Any) -> str:
    return "_".join(_norm(value).split())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _decision(
    accepted: bool,
    rejection: str | None,
    *,
    kind: str,
    band: str | None = None,
    gap_seconds: float | None = None,
    matches_founder_policy: bool = False,
    jumped: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "accepted": accepted is True,
        "rejection": None if accepted is True else rejection,
        "kind": kind,
        "band": band,
        "gap_seconds": gap_seconds,
        "matches_founder_policy": matches_founder_policy is True,
        "jumped": jumped,
        "sample_only": True,
        "offline": True,
    }
    body.update(_closed_flags())
    return body


def committed_bands_match_founder_policy() -> bool:
    """True only when the committed classifier matches the founder bands.

    This is a constant check. It does not satisfy founder condition 1.
    """
    if gaplog.YELLOW_MIN_SECONDS != FOUNDER_YELLOW_MIN_SECONDS:
        return False
    if gaplog.RED_MIN_SECONDS != FOUNDER_RED_EXCLUSIVE_MIN_SECONDS:
        return False
    params = inspect.signature(gaplog.classify_band).parameters
    if params["yellow_min"].default != gaplog.YELLOW_MIN_SECONDS:
        return False
    if params["red_min"].default != gaplog.RED_MIN_SECONDS:
        return False
    return (
        gaplog.classify_band(12.0) == "ok"
        and gaplog.classify_band(13.0) == "yellow"
        and gaplog.classify_band(300.0) == "yellow"
        and gaplog.classify_band(JUST_ABOVE_RED_SECONDS) == "red"
    )


def monitor_source_records_mono_seconds() -> bool:
    """True when the monitor source records mono_seconds from time.monotonic().

    Reads the file. Does not call the monitor loop and does not start a clock.
    """
    path = Path(__file__).resolve().parents[1] / "scripts" / "supervision_monitor.py"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "time.monotonic(" in text and "mono_seconds" in text


def classify_sample_gap(gap_seconds: Any) -> dict[str, Any]:
    """Classify one sample gap with the committed bands. Does not retune them."""
    try:
        band = gaplog.classify_band(gap_seconds)
    except gaplog.GapLogError:
        return _decision(False, "unparseable", kind="band")
    measured = float(gap_seconds)
    expected = {
        12.0: "ok",
        13.0: "yellow",
        300.0: "yellow",
        JUST_ABOVE_RED_SECONDS: "red",
    }
    known = expected.get(measured)
    matches = committed_bands_match_founder_policy() and (known is None or known == band)
    # A sample gap is "accepted" when classify_band produced the founder band
    # for the four boundary points, or any other non-negative gap under the
    # committed classifier. Acceptance here is not condition 1.
    if not committed_bands_match_founder_policy():
        return _decision(
            False,
            "band_mismatch",
            kind="band",
            band=band,
            gap_seconds=measured,
            matches_founder_policy=False,
        )
    if known is not None and known != band:
        return _decision(
            False,
            "band_mismatch",
            kind="band",
            band=band,
            gap_seconds=measured,
            matches_founder_policy=False,
        )
    return _decision(
        True,
        None,
        kind="band",
        band=band,
        gap_seconds=measured,
        matches_founder_policy=matches,
    )


def _claims_condition_1(policy: dict[str, Any]) -> bool:
    return any(
        policy.get(key) is True
        for key in (
            "condition_1_satisfied",
            "sample_policy_satisfies_condition_1",
            "dummy_tests_satisfy_condition_1",
            "implementation_satisfies_condition_1",
            "committed_constants_satisfy_condition_1",
        )
    )


def _red_is_inclusive(policy: dict[str, Any]) -> bool:
    if policy.get("red_inclusive") is True:
        return True
    boundary = _token_key(policy.get("red_boundary"))
    compare = _token_key(policy.get("red_compare"))
    if boundary in {"inclusive", "ge", ">="} or compare in {"inclusive", "ge", ">="}:
        return True
    band_at_300 = _token_key(policy.get("band_at_300") or policy.get("red_at_300"))
    return band_at_300 == "red"


def assess_policy(policy: Any) -> dict[str, Any]:
    """Refuse a declared policy that is not the founder bands.

    A declaration whose numbers match is still not founder condition 1.
    """
    if not isinstance(policy, dict):
        return _decision(False, "missing", kind="policy")
    if _claims_condition_1(policy):
        return _decision(False, "condition_1_claimed", kind="policy", matches_founder_policy=False)
    yellow_min = _number(policy.get("yellow_min_seconds"))
    yellow_max = _number(policy.get("yellow_max_seconds"))
    if "red_exclusive_min_seconds" in policy:
        red_exclusive = _number(policy.get("red_exclusive_min_seconds"))
    else:
        red_exclusive = _number(policy.get("red_min_seconds"))
    inclusive = _red_is_inclusive(policy)
    clock = _token_key(policy.get("clock") or "")
    numbers_present = yellow_min is not None and yellow_max is not None and red_exclusive is not None
    numbers_match = (
        numbers_present
        and yellow_min == FOUNDER_YELLOW_MIN_SECONDS
        and yellow_max == FOUNDER_YELLOW_MAX_SECONDS
        and red_exclusive == FOUNDER_RED_EXCLUSIVE_MIN_SECONDS
    )
    if not numbers_match:
        if (
            yellow_min == FOUNDER_YELLOW_MIN_SECONDS
            and inclusive
            and red_exclusive == FOUNDER_RED_EXCLUSIVE_MIN_SECONDS
        ):
            return _decision(False, "red_inclusive", kind="policy")
        return _decision(False, "band_mismatch", kind="policy")
    if inclusive:
        return _decision(False, "red_inclusive", kind="policy")
    if clock != ROOT_NOTE_CLOCK:
        return _decision(False, "clock_not_monotonic", kind="policy")
    if not committed_bands_match_founder_policy():
        return _decision(False, "band_mismatch", kind="policy", matches_founder_policy=False)
    return _decision(True, None, kind="policy", matches_founder_policy=True)


def assess_sequence(rows: Any) -> dict[str, Any]:
    """Accept a non-decreasing sample sequence. A backward jump is refused.

    Timestamps and mono_seconds are checked when present. A wall-clock
    timestamp that moves backwards is not monotonic, even if mono_seconds
    increases.
    """
    if rows is None:
        return _decision(False, "missing", kind="sequence")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or len(rows) == 0:
        return _decision(False, "missing", kind="sequence")
    previous_timestamp = None
    previous_mono: float | None = None
    saw_field = False
    for item in rows:
        if not isinstance(item, dict):
            return _decision(False, "unparseable", kind="sequence")
        has_timestamp = "timestamp" in item and item.get("timestamp") is not None
        has_mono = "mono_seconds" in item and item.get("mono_seconds") is not None
        if not has_timestamp and not has_mono:
            return _decision(False, "missing", kind="sequence")
        if has_timestamp:
            saw_field = True
            try:
                stamp = gaplog.parse_timestamp(str(item.get("timestamp")), field="timestamp")
            except gaplog.GapLogError:
                return _decision(False, "unparseable", kind="sequence")
            if previous_timestamp is not None and stamp < previous_timestamp:
                return _decision(False, "backward_jump", kind="sequence", jumped="timestamp")
            previous_timestamp = stamp
        if has_mono:
            saw_field = True
            mono = item.get("mono_seconds")
            if isinstance(mono, bool) or not isinstance(mono, (int, float)):
                return _decision(False, "unparseable", kind="sequence")
            measured = float(mono)
            if previous_mono is not None and measured < previous_mono:
                return _decision(False, "backward_jump", kind="sequence", jumped="mono_seconds")
            previous_mono = measured
    if not saw_field:
        return _decision(False, "missing", kind="sequence")
    return _decision(True, None, kind="sequence", matches_founder_policy=False)


def _band_specs() -> list[dict[str, Any]]:
    return [
        {"id": "gap_12_ok", "gap_seconds": 12.0, "band": "ok"},
        {"id": "gap_13_yellow", "gap_seconds": 13.0, "band": "yellow"},
        {"id": "gap_300_yellow", "gap_seconds": 300.0, "band": "yellow"},
        {"id": "gap_just_above_300_red", "gap_seconds": JUST_ABOVE_RED_SECONDS, "band": "red"},
    ]


def _sequence_specs() -> list[dict[str, Any]]:
    return [
        {
            "id": "sequence_non_decreasing",
            "rows": [
                {"timestamp": "2026-02-01T00:00:00Z", "mono_seconds": 0.0},
                {"timestamp": "2026-02-01T00:00:13Z", "mono_seconds": 13.0},
                {"timestamp": "2026-02-01T00:05:00Z", "mono_seconds": 300.0},
                {"timestamp": "2026-02-01T00:05:00Z", "mono_seconds": 300.0},
            ],
            "accepted": True,
            "rejection": None,
            "jumped": None,
        },
        {
            "id": "wall_clock_backward",
            "rows": [
                {"timestamp": "2026-02-01T00:05:00Z", "mono_seconds": 300.0},
                {"timestamp": "2026-02-01T00:04:00Z", "mono_seconds": 301.0},
            ],
            "accepted": False,
            "rejection": "backward_jump",
            "jumped": "timestamp",
        },
        {
            "id": "mono_seconds_backward",
            "rows": [
                {"timestamp": "2026-02-01T00:00:00Z", "mono_seconds": 20.0},
                {"timestamp": "2026-02-01T00:00:13Z", "mono_seconds": 19.0},
            ],
            "accepted": False,
            "rejection": "backward_jump",
            "jumped": "mono_seconds",
        },
    ]


def _policy_specs() -> list[dict[str, Any]]:
    founder = {
        "yellow_min_seconds": FOUNDER_YELLOW_MIN_SECONDS,
        "yellow_max_seconds": FOUNDER_YELLOW_MAX_SECONDS,
        "red_exclusive_min_seconds": FOUNDER_RED_EXCLUSIVE_MIN_SECONDS,
        "clock": "monotonic",
        "sample_only": True,
        "offline": True,
    }
    yellow_10 = dict(founder)
    yellow_10["yellow_min_seconds"] = 10.0
    red_inclusive = dict(founder)
    red_inclusive["red_inclusive"] = True
    called = dict(founder)
    called["condition_1_satisfied"] = True
    called["committed_constants_satisfy_condition_1"] = True
    return [
        {
            "id": "founder_numbers_not_condition_1",
            "policy": founder,
            "accepted": True,
            "rejection": None,
            "matches_founder_policy": True,
        },
        {
            "id": "yellow_starts_at_10",
            "policy": yellow_10,
            "accepted": False,
            "rejection": "band_mismatch",
            "matches_founder_policy": False,
        },
        {
            "id": "red_inclusive_at_300",
            "policy": red_inclusive,
            "accepted": False,
            "rejection": "red_inclusive",
            "matches_founder_policy": False,
        },
        {
            "id": "constants_called_condition_1",
            "policy": called,
            "accepted": False,
            "rejection": "condition_1_claimed",
            "matches_founder_policy": False,
        },
    ]


def _json_number(value: Any) -> Any:
    """Use the same float JSON will store, so a later reload still matches."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return json.loads(json.dumps(float(value)))


def _sample_row(row_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": row_id,
        "accepted": decision.get("accepted") is True,
        "rejection": decision.get("rejection"),
        "kind": decision.get("kind"),
        "band": decision.get("band"),
        "gap_seconds": _json_number(decision.get("gap_seconds")),
        "matches_founder_policy": decision.get("matches_founder_policy") is True,
        "jumped": decision.get("jumped"),
        "sample_only": True,
        "offline": True,
    }
    row.update(_sample_flags())
    return row


def canonical_samples() -> list[dict[str, Any]]:
    """Classify the fixed samples. No clock and no live soak."""
    rows: list[dict[str, Any]] = []
    for spec in _band_specs():
        decision = classify_sample_gap(spec["gap_seconds"])
        rows.append(_sample_row(spec["id"], decision))
    for spec in _sequence_specs():
        decision = assess_sequence(spec["rows"])
        rows.append(_sample_row(spec["id"], decision))
    for spec in _policy_specs():
        decision = assess_policy(spec["policy"])
        rows.append(_sample_row(spec["id"], decision))
    return rows


def _compare_keys() -> tuple[str, ...]:
    return (
        "id",
        "accepted",
        "rejection",
        "kind",
        "band",
        "gap_seconds",
        "matches_founder_policy",
        "jumped",
        "sample_only",
        "offline",
    )


def samples_match(rows: Any) -> bool:
    expected = canonical_samples()
    if not isinstance(rows, list) or len(rows) != len(expected):
        return False
    for got, want in zip(rows, expected):
        if not isinstance(got, dict):
            return False
        for key in _compare_keys():
            if got.get(key) != want.get(key):
                return False
        for key, value in _sample_flags().items():
            if got.get(key) != value:
                return False
    return True


def run_offline_exercise() -> dict[str, Any]:
    """Run the fixed samples. A pass does not satisfy founder condition 1."""
    try:
        rows = canonical_samples()
        bands_match = committed_bands_match_founder_policy()
        monitor_ok = monitor_source_records_mono_seconds()
    except Exception:
        return {"ok": False, "detail": "import_failed"}
    by_id = {row["id"]: row for row in rows}
    bands_ok = all(
        by_id[spec["id"]]["accepted"] is True
        and by_id[spec["id"]]["band"] == spec["band"]
        and by_id[spec["id"]]["rejection"] is None
        for spec in _band_specs()
    )
    sequences_ok = all(
        by_id[spec["id"]]["accepted"] is spec["accepted"]
        and by_id[spec["id"]]["rejection"] == spec["rejection"]
        and by_id[spec["id"]]["jumped"] == spec["jumped"]
        for spec in _sequence_specs()
    )
    policies_ok = all(
        by_id[spec["id"]]["accepted"] is spec["accepted"]
        and by_id[spec["id"]]["rejection"] == spec["rejection"]
        and by_id[spec["id"]]["matches_founder_policy"] is spec["matches_founder_policy"]
        for spec in _policy_specs()
    )
    flags_closed = all(
        row.get("condition_1_satisfied") is False and row.get("can_start_clock") is False for row in rows
    )
    backward_rejected = (
        by_id["wall_clock_backward"]["rejection"] == "backward_jump"
        and by_id["mono_seconds_backward"]["rejection"] == "backward_jump"
    )
    alternate_rejected = (
        by_id["yellow_starts_at_10"]["rejection"] == "band_mismatch"
        and by_id["red_inclusive_at_300"]["rejection"] == "red_inclusive"
    )
    claim_rejected = by_id["constants_called_condition_1"]["rejection"] == "condition_1_claimed"
    ok = (
        bands_match
        and monitor_ok
        and bands_ok
        and sequences_ok
        and policies_ok
        and flags_closed
        and backward_rejected
        and alternate_rejected
        and claim_rejected
        and by_id["founder_numbers_not_condition_1"]["accepted"] is True
        and by_id["founder_numbers_not_condition_1"]["condition_1_satisfied"] is False
    )
    if not ok:
        return {"ok": False, "detail": "classification_failed"}
    return {
        "ok": True,
        "detail": SUCCESS_DETAIL,
        "classifies_sample_policy_bands_passed": True,
        "monotonic_sample_sequence_passed": True,
        "declared_bands_match_founder_policy": True,
        "backward_jump_rejected": True,
        "alternate_bands_rejected": True,
        "red_inclusive_rejected": True,
        "condition_1_claim_rejected": True,
        "monitor_source_records_mono_seconds": True,
        "samples": rows,
    }


def _refused_claims() -> list[dict[str, Any]]:
    common = _closed_flags()
    specs = (
        ("sample_policy_called_condition_1", "sample_policy_claimed_as_condition_1"),
        ("committed_constants_called_condition_1", "committed_constants_claimed_as_condition_1"),
        ("alternate_bands_called_founder_policy", "alternate_bands_called_founder_policy"),
        ("backward_clock_called_monotonic", "backward_clock_called_monotonic"),
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
        "gap_logger": GAP_LOGGER,
        "monitor": MONITOR,
        "detail": detail,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "implementation_present": implementation_present and passed,
        "classifies_sample_policy_bands_passed": passed,
        "monotonic_sample_sequence_passed": passed,
        "declared_bands_match_founder_policy": passed,
        "backward_jump_rejected": passed,
        "alternate_bands_rejected": passed,
        "red_inclusive_rejected": passed,
        "condition_1_claim_rejected": passed,
        "monitor_source_records_mono_seconds": passed,
        "yellow_min_seconds": FOUNDER_YELLOW_MIN_SECONDS,
        "yellow_max_seconds": FOUNDER_YELLOW_MAX_SECONDS,
        "red_exclusive_min_seconds": FOUNDER_RED_EXCLUSIVE_MIN_SECONDS,
        "red_boundary": "exclusive",
        "clock_required": ROOT_NOTE_CLOCK,
        "samples": samples if passed and isinstance(samples, list) else [],
        "sample_only": True,
        "offline": True,
        "hole": HOLE,
        "note": NOTE,
        "sample_policy_claimed_as_condition_1": False,
        "committed_constants_claimed_as_condition_1": False,
        "alternate_bands_called_founder_policy": False,
        "backward_clock_called_monotonic": False,
        "pass_or_start_claimed": False,
        "refused_claims": _refused_claims(),
    }
    block.update(_closed_flags())
    return block


def scaffold_status_for_root(script_present: bool) -> dict[str, Any]:
    """Skip the check when the inspected root has no policy checker."""
    if not script_present:
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    return stable_scaffold_status()


def stable_scaffold_status(*, force: bool = False) -> dict[str, Any]:
    """Deterministic sample check. No timings and no live soak."""
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
    detail = measured.get("detail") if measured.get("detail") in FAILURE_DETAILS else "classification_failed"
    return _scaffold_shell(str(detail), ok=False, implementation_present=False)


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


def _claim_names_alternate_bands(claim: dict[str, Any]) -> bool:
    if claim.get("alternate_bands_accepted") is True or claim.get("red_inclusive") is True:
        return True
    yellow_min = _number(claim.get("yellow_min_seconds"))
    if yellow_min is not None and yellow_min != FOUNDER_YELLOW_MIN_SECONDS:
        return True
    if _red_is_inclusive(claim):
        return True
    return False


def _claim_names_backward_clock(claim: dict[str, Any]) -> bool:
    if claim.get("backward_clock_is_monotonic") is True:
        return True
    clock = _token_key(claim.get("clock") or "")
    if clock in {"wall", "wall_clock", "utc", "system"}:
        return True
    rows = claim.get("sequence")
    if isinstance(rows, list):
        decision = assess_sequence(rows)
        return decision.get("rejection") == "backward_jump"
    return False


def annotate_scaffold_claim(block: dict[str, Any], claim: dict[str, Any] | None) -> None:
    """Record a pretense. Closed flags are applied again by the caller."""
    block["sample_policy_claimed_as_condition_1"] = False
    block["committed_constants_claimed_as_condition_1"] = False
    block["alternate_bands_called_founder_policy"] = False
    block["backward_clock_called_monotonic"] = False
    block["pass_or_start_claimed"] = False
    if not isinstance(claim, dict):
        return
    if _claims_condition_1(claim):
        block["sample_policy_claimed_as_condition_1"] = True
    if claim.get("committed_constants_satisfy_condition_1") is True or claim.get(
        "declared_bands_match_founder_policy_satisfies_condition_1"
    ) is True:
        block["committed_constants_claimed_as_condition_1"] = True
        block["sample_policy_claimed_as_condition_1"] = True
    if _claim_names_alternate_bands(claim):
        block["alternate_bands_called_founder_policy"] = True
    if _claim_names_backward_clock(claim):
        block["backward_clock_called_monotonic"] = True
    if _claim_says_pass_or_start(claim):
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
    if key == "alternate_bands_accepted":
        return "supervision_policy_band_refused"
    if key == "backward_clock_is_monotonic":
        return "supervision_policy_clock_not_monotonic"
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
        "condition_3_satisfied",
        "sample_pack_satisfies_condition_3",
        "dummy_tests_satisfy_condition_3",
        "implementation_satisfies_condition_3",
        "packs_live_soak_evidence",
    }:
        return "condition_3_unsatisfied"
    if key == "local_only_counts_as_public_evidence":
        return "local_only_refused"
    if key == "scaffold_sha256sums_is_soak_evidence":
        return "scaffold_sha256sums_not_soak_evidence"
    if key in {
        "condition_4_satisfied",
        "sample_classification_satisfies_condition_4",
        "dummy_tests_satisfy_condition_4",
        "implementation_satisfies_condition_4",
        "attributes_live_soak_failure",
    }:
        return "condition_4_unsatisfied"
    if key in {
        "is_supervisor_watchdog_of_live_supervisor",
        "is_live_l2_2_supervisor",
        "is_live_l2_2_supervisor_watchdog",
        "live_supervisor_process",
        "live_soak_process",
        "watches_live_soak",
    }:
        return "supervision_policy"
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
    return "supervision_policy"


def scaffold_violations(block: Any, *, require_success: bool = True) -> list[str]:
    """Reject a report that treats the sample policy check as founder condition 1."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["supervision_policy"]
    for key, expected in _closed_flags().items():
        if block.get(key) != expected:
            violations.append(_flag_violation(key))
    constants = {
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "gap_logger": GAP_LOGGER,
        "monitor": MONITOR,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "hole": HOLE,
        "note": NOTE,
        "yellow_min_seconds": FOUNDER_YELLOW_MIN_SECONDS,
        "yellow_max_seconds": FOUNDER_YELLOW_MAX_SECONDS,
        "red_exclusive_min_seconds": FOUNDER_RED_EXCLUSIVE_MIN_SECONDS,
        "red_boundary": "exclusive",
        "clock_required": ROOT_NOTE_CLOCK,
        "sample_only": True,
        "offline": True,
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            violations.append("supervision_policy")
    for key in (
        "sample_policy_claimed_as_condition_1",
        "committed_constants_claimed_as_condition_1",
        "alternate_bands_called_founder_policy",
        "backward_clock_called_monotonic",
        "pass_or_start_claimed",
    ):
        if not isinstance(block.get(key), bool):
            violations.append("supervision_policy")
    claims = block.get("refused_claims")
    expected_labels = [
        "sample_policy_called_condition_1",
        "committed_constants_called_condition_1",
        "alternate_bands_called_founder_policy",
        "backward_clock_called_monotonic",
    ]
    if not isinstance(claims, list):
        violations.append("supervision_policy")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if labels != expected_labels:
            violations.append("supervision_policy")
        else:
            flags = (
                "sample_policy_claimed_as_condition_1",
                "committed_constants_claimed_as_condition_1",
                "alternate_bands_called_founder_policy",
                "backward_clock_called_monotonic",
            )
            for item, flag in zip(claims, flags):
                if item.get(flag) is not True or item.get("condition_1_satisfied") is not False:
                    violations.append("condition_1_unsatisfied")
                if item.get("committed_constants_satisfy_condition_1") is not False:
                    violations.append("condition_1_unsatisfied")
                if item.get("l2_2_status") != "NOT_STARTED" or item.get("can_start_clock") is not False:
                    violations.append("offline_probe_is_not_a_start")
    detail = block.get("detail")
    ok = block.get("ok")
    passed_keys = (
        "classifies_sample_policy_bands_passed",
        "monotonic_sample_sequence_passed",
        "declared_bands_match_founder_policy",
        "backward_jump_rejected",
        "alternate_bands_rejected",
        "red_inclusive_rejected",
        "condition_1_claim_rejected",
        "monitor_source_records_mono_seconds",
        "implementation_present",
    )
    if require_success:
        if ok is not True or detail != SUCCESS_DETAIL or any(block.get(key) is not True for key in passed_keys):
            violations.append("supervision_policy")
        elif not samples_match(block.get("samples")):
            violations.append("supervision_policy")
    else:
        if detail not in FAILURE_DETAILS or not isinstance(ok, bool):
            violations.append("supervision_policy")
        elif ok is True and (
            detail != SUCCESS_DETAIL
            or any(block.get(key) is not True for key in passed_keys)
            or not samples_match(block.get("samples"))
        ):
            violations.append("supervision_policy")
        elif ok is not True and (
            any(block.get(key) is not False for key in passed_keys) or block.get("samples") not in ([], None)
        ):
            violations.append("supervision_policy")
    return violations


def _summary_flags(decision: dict[str, Any], *, bands_passed: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": True,
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "gap_logger": GAP_LOGGER,
        "accepted": decision.get("accepted") is True,
        "rejection": decision.get("rejection"),
        "kind": decision.get("kind"),
        "band": decision.get("band"),
        "gap_seconds": decision.get("gap_seconds"),
        "matches_founder_policy": decision.get("matches_founder_policy") is True,
        "jumped": decision.get("jumped"),
        "sample_only": True,
        "offline": True,
        "classifies_sample_policy_bands_passed": bands_passed,
        "monotonic_sample_sequence_passed": False,
        "declared_bands_match_founder_policy": committed_bands_match_founder_policy(),
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
        "classifies_sample_policy_bands_passed": False,
        "monotonic_sample_sequence_passed": False,
        "declared_bands_match_founder_policy": False,
        "note": NOTE,
    }
    body.update(_closed_flags())
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", action="store_true", help="classify the fixed sample set")
    parser.add_argument("--gap-seconds", type=float, default=None, help="classify one sample gap")
    parser.add_argument("--policy", default=None, help="JSON policy declaration to refuse or record")
    parser.add_argument("--sequence", default=None, help="JSON list of timestamp and/or mono_seconds samples")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.samples:
        status = stable_scaffold_status()
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return 0 if status.get("ok") is True else 2
    if args.policy is not None:
        try:
            payload = json.loads(args.policy)
        except json.JSONDecodeError:
            print(json.dumps(_error_summary("policy_not_json"), ensure_ascii=False))
            return 2
        print(json.dumps(_summary_flags(assess_policy(payload), bands_passed=False), ensure_ascii=False, sort_keys=True))
        return 0
    if args.sequence is not None:
        try:
            payload = json.loads(args.sequence)
        except json.JSONDecodeError:
            print(json.dumps(_error_summary("sequence_not_json"), ensure_ascii=False))
            return 2
        decision = assess_sequence(payload)
        body = _summary_flags(decision, bands_passed=False)
        body["monotonic_sample_sequence_passed"] = False
        print(json.dumps(body, ensure_ascii=False, sort_keys=True))
        return 0
    if args.gap_seconds is None:
        print(json.dumps(_error_summary("sample_required"), ensure_ascii=False))
        return 2
    decision = classify_sample_gap(args.gap_seconds)
    canonical_gap = args.gap_seconds in {12.0, 13.0, 300.0, JUST_ABOVE_RED_SECONDS}
    known = decision.get("accepted") is True and canonical_gap
    print(json.dumps(_summary_flags(decision, bands_passed=known), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
