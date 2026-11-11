#!/usr/bin/env python3
"""Sample public evidence-pack check for founder condition 3.

Validates synthetic packs only. A sample pack counts here when it is labeled
sample/offline, its publication is public, and it includes all three pieces:
final metrics, a log summary, and a SHA list. Digests use
scripts/evidence_sha256sums.py. LOCAL_ONLY is refused and does not count.
A pack missing any of the three pieces is refused. The committed
docs/progress/l2_2/SHA256SUMS.json binds scaffold bytes only. It is not a
live soak evidence pack.

A passing sample validation does not satisfy founder condition 3, does not
pack live soak evidence, and does not start the clock.

  python3 scripts/public_evidence_pack.py --samples
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

TOOL = "scripts/public_evidence_pack.py"
ACTION = "validate_sample_public_pack"
DUT = "synthetic_sample_public_pack"
HASHER = "scripts/evidence_sha256sums.py"
FOUNDER_CONDITION_ID = "public_evidence"
SCAFFOLD_SUMS_PATH = "docs/progress/l2_2/SHA256SUMS.json"
SUCCESS_DETAIL = "implementation_exists_sample_public_pack_validated"
FAILURE_DETAILS = frozenset(
    {
        SUCCESS_DETAIL,
        "script_missing",
        "validation_failed",
        "import_failed",
        "hasher_import_failed",
    }
)
HOLE = "sample_public_pack_is_not_live_soak_evidence"
NOTE = (
    "This module validates sample public-shaped packs only. "
    "A sample pack needs publication public plus final metrics, a log summary, and a SHA list. "
    "Digests are SHA-256 from scripts/evidence_sha256sums.py. "
    "LOCAL_ONLY is refused and does not count. "
    "A pack missing any of the three pieces is refused. "
    "docs/progress/l2_2/SHA256SUMS.json binds scaffold bytes only and is not live soak evidence. "
    "Validating these samples does not satisfy founder condition 3 and does not start L2-2."
)
PIECES = ("final_metrics", "log_summary", "sha_list")
SAMPLE_METRICS = {
    "label": "sample_public_pack",
    "sample_only": True,
    "offline": True,
    "final": True,
    "wall_elapsed_s": 0,
    "clock_state": "NOT_STARTED",
    "production_7x24": "NOT_ACCEPTED",
}
SAMPLE_LOG_SUMMARY = (
    "sample log summary\n"
    "clock NOT_STARTED\n"
    "production 7x24 NOT_ACCEPTED\n"
    "not a live soak\n"
)
ROOT = Path(__file__).resolve().parents[1]
_CACHE: dict[str, Any] | None = None
_PACK_CACHE: dict[str, Any] | None = None


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def _token_key(value: Any) -> str:
    return "_".join(_norm(value).split())


def _publication(value: Any) -> str:
    token = _norm(value).replace(" ", "")
    if token == "localonly":
        return "local_only"
    if token == "public":
        return "public"
    keyed = _token_key(value)
    return keyed


def _closed_flags() -> dict[str, Any]:
    return {
        "condition_3_satisfied": False,
        "sample_pack_satisfies_condition_3": False,
        "dummy_tests_satisfy_condition_3": False,
        "implementation_satisfies_condition_3": False,
        "packs_live_soak_evidence": False,
        "local_only_counts_as_public_evidence": False,
        "scaffold_sha256sums_is_soak_evidence": False,
        "condition_4_satisfied": False,
        "attributes_live_soak_failure": False,
        "dummy_tests_satisfy_condition_4": False,
        "implementation_satisfies_condition_4": False,
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


def _sha256_bytes(payload: bytes) -> str:
    """Hash bytes with evidence_sha256sums.sha256_file. No soak file is written."""
    from evidence_sha256sums import sha256_file

    with tempfile.TemporaryDirectory(prefix="l2-sample-pack-") as directory:
        path = Path(directory) / "blob"
        path.write_bytes(payload)
        return sha256_file(path)


def _metrics_bytes() -> bytes:
    return json.dumps(SAMPLE_METRICS, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sample_public_pack() -> dict[str, Any]:
    """The fixed sample public pack. Hashes are scaffold-sample bytes only."""
    global _PACK_CACHE
    if _PACK_CACHE is not None:
        return json.loads(json.dumps(_PACK_CACHE))
    metrics = _metrics_bytes()
    summary = SAMPLE_LOG_SUMMARY.encode("utf-8")
    pack = {
        "publication": "public",
        "sample_only": True,
        "offline": True,
        "evidence_class": "sample",
        "final_metrics": json.loads(json.dumps(SAMPLE_METRICS)),
        "log_summary": SAMPLE_LOG_SUMMARY,
        "sha_list": [
            {"path": "sample/final_metrics.json", "sha256": _sha256_bytes(metrics)},
            {"path": "sample/log_summary.txt", "sha256": _sha256_bytes(summary)},
        ],
    }
    _PACK_CACHE = json.loads(json.dumps(pack))
    return json.loads(json.dumps(pack))


def _sha_list_ok(value: Any) -> bool:
    if not isinstance(value, list) or len(value) == 0:
        return False
    for item in value:
        if not isinstance(item, dict):
            return False
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path, str) or not path.strip():
            return False
        if not isinstance(digest, str) or len(digest) != 64:
            return False
        if any(char not in "0123456789abcdef" for char in digest.lower()):
            return False
    return True


def _piece_present(pack: dict[str, Any], key: str) -> bool:
    if key not in pack:
        return False
    value = pack.get(key)
    if value is None:
        return False
    if key == "final_metrics":
        return isinstance(value, dict) and len(value) > 0
    if key == "log_summary":
        if isinstance(value, str):
            return bool(value.strip())
        return isinstance(value, dict) and len(value) > 0
    if key == "sha_list":
        return _sha_list_ok(value)
    return False


def _missing_pieces(pack: dict[str, Any]) -> list[str]:
    return [key for key in PIECES if not _piece_present(pack, key)]


def _names_scaffold_sums(pack: dict[str, Any]) -> bool:
    if pack.get("scaffold_sha256sums_is_soak_evidence") is True:
        return True
    role = _token_key(pack.get("role") or pack.get("kind") or "")
    if role in {"scaffold_sha256sums", "sha256sums", "scaffold_sums"}:
        return True
    for key in ("path", "source", "pack_path"):
        raw = str(pack.get(key) or "").replace("\\", "/")
        if raw.endswith(SCAFFOLD_SUMS_PATH):
            return True
    files = pack.get("files")
    if (
        isinstance(files, list)
        and len(files) > 0
        and "final_metrics" not in pack
        and "log_summary" not in pack
        and all(isinstance(item, dict) and isinstance(item.get("sha256"), str) for item in files)
    ):
        return True
    return False


def _is_sample(pack: dict[str, Any]) -> bool:
    if pack.get("sample_only") is True or pack.get("offline") is True:
        if _token_key(pack.get("evidence_class") or "sample") in {"sample", "scaffold", ""}:
            return pack.get("sample_only") is True or pack.get("offline") is True
    if pack.get("sample_only") is True:
        return True
    return _token_key(pack.get("evidence_class")) == "sample" and pack.get("offline") is True


def _decision(
    accepted: bool,
    rejection: str | None,
    *,
    missing: list[str] | None = None,
    sample_only: bool = True,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "accepted": accepted is True,
        "rejection": None if accepted is True else rejection,
        "missing": list(missing or []),
        "sample_only": sample_only is True,
        "offline": True,
        "local_only_pack_rejected": rejection == "local_only",
        "pieces": list(PIECES),
    }
    body.update(_closed_flags())
    return body


def validate_pack(pack: Any) -> dict[str, Any]:
    """Validate one pack. A sample pass does not satisfy founder condition 3."""
    if not isinstance(pack, dict):
        return _decision(False, "missing_piece", missing=list(PIECES), sample_only=False)
    sample_only = pack.get("sample_only") is True or pack.get("offline") is True
    if _names_scaffold_sums(pack):
        return _decision(
            False,
            "scaffold_sha256sums_not_soak_evidence",
            missing=_missing_pieces(pack),
            sample_only=sample_only,
        )
    publication = _publication(pack.get("publication"))
    if publication == "local_only":
        return _decision(False, "local_only", missing=_missing_pieces(pack), sample_only=sample_only)
    missing = _missing_pieces(pack)
    if len(missing) == 1:
        return _decision(False, "missing_" + missing[0], missing=missing, sample_only=sample_only)
    if len(missing) > 1:
        return _decision(False, "missing_piece", missing=missing, sample_only=sample_only)
    if publication != "public":
        return _decision(False, "not_public", sample_only=sample_only)
    if not _is_sample(pack):
        return _decision(False, "not_sample", sample_only=False)
    if (
        pack.get("packs_live_soak_evidence") is True
        or pack.get("condition_3_satisfied") is True
        or pack.get("dummy_tests_satisfy_condition_3") is True
        or pack.get("implementation_satisfies_condition_3") is True
        or pack.get("sample_pack_satisfies_condition_3") is True
    ):
        return _decision(False, "live_soak_pack_refused", sample_only=sample_only)
    return _decision(True, None, sample_only=True)


def _sample_flags() -> dict[str, Any]:
    closed = _closed_flags()
    keys = (
        "condition_3_satisfied",
        "packs_live_soak_evidence",
        "dummy_tests_satisfy_condition_3",
        "implementation_satisfies_condition_3",
        "local_only_counts_as_public_evidence",
        "scaffold_sha256sums_is_soak_evidence",
        "condition_4_satisfied",
        "condition_2_satisfied",
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


def _with_piece_removed(pack: dict[str, Any], key: str) -> dict[str, Any]:
    copy = json.loads(json.dumps(pack))
    copy.pop(key, None)
    return copy


def _sample_specs() -> list[dict[str, Any]]:
    complete = sample_public_pack()
    local_only = json.loads(json.dumps(complete))
    local_only["publication"] = "LOCAL_ONLY"
    bare = {"publication": "public", "sample_only": True, "offline": True, "evidence_class": "sample"}
    sums = {
        "role": "scaffold_sha256sums",
        "path": SCAFFOLD_SUMS_PATH,
        "files": [{"path": "docs/progress/l2_2/README.md", "sha256": "0" * 64, "bytes": 1}],
    }
    live = json.loads(json.dumps(complete))
    live["sample_only"] = False
    live["offline"] = False
    live["evidence_class"] = "host_observation"
    live["packs_live_soak_evidence"] = True
    return [
        {
            "id": "sample_public_complete",
            "pack": complete,
            "accepted": True,
            "rejection": None,
            "missing": [],
        },
        {
            "id": "local_only_with_all_pieces",
            "pack": local_only,
            "accepted": False,
            "rejection": "local_only",
            "missing": [],
        },
        {
            "id": "missing_final_metrics",
            "pack": _with_piece_removed(complete, "final_metrics"),
            "accepted": False,
            "rejection": "missing_final_metrics",
            "missing": ["final_metrics"],
        },
        {
            "id": "missing_log_summary",
            "pack": _with_piece_removed(complete, "log_summary"),
            "accepted": False,
            "rejection": "missing_log_summary",
            "missing": ["log_summary"],
        },
        {
            "id": "missing_sha_list",
            "pack": _with_piece_removed(complete, "sha_list"),
            "accepted": False,
            "rejection": "missing_sha_list",
            "missing": ["sha_list"],
        },
        {
            "id": "missing_all_three",
            "pack": bare,
            "accepted": False,
            "rejection": "missing_piece",
            "missing": list(PIECES),
        },
        {
            "id": "scaffold_sha256sums",
            "pack": sums,
            "accepted": False,
            "rejection": "scaffold_sha256sums_not_soak_evidence",
            "missing": list(PIECES),
        },
        {
            "id": "live_shaped_pack",
            "pack": live,
            "accepted": False,
            "rejection": "not_sample",
            "missing": [],
        },
    ]


def _sample_row(spec: dict[str, Any], validated: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": spec["id"],
        "accepted": validated.get("accepted") is True,
        "rejection": validated.get("rejection"),
        "missing": list(validated.get("missing") or []),
        "sample_only": validated.get("sample_only") is True,
        "offline": True,
        "local_only_pack_rejected": validated.get("rejection") == "local_only",
    }
    row.update(_sample_flags())
    return row


def canonical_samples() -> list[dict[str, Any]]:
    """Validate the fixed sample set. No clock and no live soak."""
    rows: list[dict[str, Any]] = []
    for spec in _sample_specs():
        rows.append(_sample_row(spec, validate_pack(spec["pack"])))
    return rows


def samples_match(rows: Any) -> bool:
    expected = canonical_samples()
    if not isinstance(rows, list) or len(rows) != len(expected):
        return False
    for got, want in zip(rows, expected):
        if not isinstance(got, dict):
            return False
        for key in ("id", "accepted", "rejection", "missing", "sample_only", "offline", "local_only_pack_rejected"):
            if got.get(key) != want.get(key):
                return False
        for key, value in _sample_flags().items():
            if got.get(key) != value:
                return False
    return True


def committed_scaffold_sums_refused(root: Path | None = None) -> bool:
    """The committed scaffold hasher output is not a soak evidence pack."""
    path = (root or ROOT) / SCAFFOLD_SUMS_PATH
    if not path.is_file():
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(document, dict):
        return False
    document = json.loads(json.dumps(document))
    document["path"] = SCAFFOLD_SUMS_PATH
    decision = validate_pack(document)
    return (
        decision.get("accepted") is False
        and decision.get("rejection") == "scaffold_sha256sums_not_soak_evidence"
        and decision.get("scaffold_sha256sums_is_soak_evidence") is False
        and decision.get("packs_live_soak_evidence") is False
        and decision.get("condition_3_satisfied") is False
    )


def run_offline_exercise() -> dict[str, Any]:
    """Validate the fixed samples. A pass does not satisfy founder condition 3."""
    try:
        rows = canonical_samples()
    except Exception:
        return {"ok": False, "detail": "hasher_import_failed"}
    by_id = {row["id"]: row for row in rows}
    complete = by_id["sample_public_complete"]
    local_only = by_id["local_only_with_all_pieces"]
    sums = by_id["scaffold_sha256sums"]
    live = by_id["live_shaped_pack"]
    missing_ok = (
        by_id["missing_final_metrics"]["rejection"] == "missing_final_metrics"
        and by_id["missing_log_summary"]["rejection"] == "missing_log_summary"
        and by_id["missing_sha_list"]["rejection"] == "missing_sha_list"
        and by_id["missing_all_three"]["rejection"] == "missing_piece"
        and all(row["accepted"] is False for row in rows if row["id"] != "sample_public_complete")
    )
    flags_closed = all(
        row.get("condition_3_satisfied") is False and row.get("can_start_clock") is False for row in rows
    )
    sums_refused = committed_scaffold_sums_refused()
    ok = (
        complete["accepted"] is True
        and complete["rejection"] is None
        and local_only["accepted"] is False
        and local_only["rejection"] == "local_only"
        and local_only["local_only_pack_rejected"] is True
        and sums["rejection"] == "scaffold_sha256sums_not_soak_evidence"
        and live["accepted"] is False
        and live["rejection"] == "not_sample"
        and missing_ok
        and flags_closed
        and sums_refused
        and all(row.get("scaffold_sha256sums_is_soak_evidence") is False for row in rows)
        and all(row.get("local_only_counts_as_public_evidence") is False for row in rows)
    )
    if not ok:
        return {"ok": False, "detail": "validation_failed"}
    return {
        "ok": True,
        "detail": SUCCESS_DETAIL,
        "classifies_or_validates_sample_public_pack_passed": True,
        "local_only_pack_rejected": True,
        "missing_piece_rejected": True,
        "scaffold_sha256sums_refused": True,
        "committed_scaffold_sums_refused": True,
        "samples": rows,
    }


def _refused_claims() -> list[dict[str, Any]]:
    common = _closed_flags()
    specs = (
        ("sample_pack_called_condition_3", "sample_pack_claimed_as_condition_3"),
        ("local_only_called_public_evidence", "local_only_called_public_evidence"),
        ("scaffold_sha256sums_called_soak_evidence", "scaffold_sums_called_soak_evidence"),
        ("sample_called_live_soak_pack", "live_soak_pack_claimed"),
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
        detail = "validation_failed"
    passed = ok is True and detail == SUCCESS_DETAIL
    block: dict[str, Any] = {
        "ok": passed,
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "hasher": HASHER,
        "detail": detail,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "scaffold_sha256sums_path": SCAFFOLD_SUMS_PATH,
        "implementation_present": implementation_present and passed,
        "classifies_or_validates_sample_public_pack_passed": passed,
        "local_only_pack_rejected": passed,
        "missing_piece_rejected": passed,
        "scaffold_sha256sums_refused": passed,
        "committed_scaffold_sums_refused": passed,
        "required_pieces": list(PIECES),
        "samples": samples if passed and isinstance(samples, list) else [],
        "sample_only": True,
        "offline": True,
        "hole": HOLE,
        "note": NOTE,
        "sample_pack_claimed_as_condition_3": False,
        "local_only_called_public_evidence": False,
        "scaffold_sums_called_soak_evidence": False,
        "live_soak_pack_claimed": False,
        "pass_or_start_claimed": False,
        "refused_claims": _refused_claims(),
    }
    block.update(_closed_flags())
    return block


def scaffold_status_for_root(script_present: bool) -> dict[str, Any]:
    """Skip validation when the inspected root has no pack checker."""
    if not script_present:
        return _scaffold_shell("script_missing", ok=False, implementation_present=False)
    return stable_scaffold_status()


def stable_scaffold_status(*, force: bool = False) -> dict[str, Any]:
    """Deterministic sample validation. No timings and no live soak."""
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
    detail = measured.get("detail") if measured.get("detail") in FAILURE_DETAILS else "validation_failed"
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


def annotate_scaffold_claim(block: dict[str, Any], claim: dict[str, Any] | None) -> None:
    """Record a pretense. Closed flags are applied again by the caller."""
    block["sample_pack_claimed_as_condition_3"] = False
    block["local_only_called_public_evidence"] = False
    block["scaffold_sums_called_soak_evidence"] = False
    block["live_soak_pack_claimed"] = False
    block["pass_or_start_claimed"] = False
    if not isinstance(claim, dict):
        return
    if (
        claim.get("condition_3_satisfied") is True
        or claim.get("sample_pack_satisfies_condition_3") is True
        or claim.get("dummy_tests_satisfy_condition_3") is True
        or claim.get("implementation_satisfies_condition_3") is True
    ):
        block["sample_pack_claimed_as_condition_3"] = True
    if claim.get("local_only_counts_as_public_evidence") is True or _publication(claim.get("publication")) == "local_only":
        block["local_only_called_public_evidence"] = True
    if claim.get("scaffold_sha256sums_is_soak_evidence") is True:
        block["scaffold_sums_called_soak_evidence"] = True
    if claim.get("packs_live_soak_evidence") is True:
        block["live_soak_pack_claimed"] = True
    if _claim_says_pass_or_start(claim):
        block["pass_or_start_claimed"] = True


def _flag_violation(key: str) -> str:
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
        "attributes_live_soak_failure",
        "dummy_tests_satisfy_condition_4",
        "implementation_satisfies_condition_4",
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
        return "public_evidence_pack"
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
    return "public_evidence_pack"


def scaffold_violations(block: Any, *, require_success: bool = True) -> list[str]:
    """Reject a report that treats a sample pack as founder condition 3."""
    violations: list[str] = []
    if not isinstance(block, dict):
        return ["public_evidence_pack"]
    for key, expected in _closed_flags().items():
        if block.get(key) != expected:
            violations.append(_flag_violation(key))
    constants = {
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "hasher": HASHER,
        "founder_condition_id": FOUNDER_CONDITION_ID,
        "scaffold_sha256sums_path": SCAFFOLD_SUMS_PATH,
        "hole": HOLE,
        "note": NOTE,
        "required_pieces": list(PIECES),
        "sample_only": True,
        "offline": True,
    }
    for key, expected in constants.items():
        if block.get(key) != expected:
            violations.append("public_evidence_pack")
    for key in (
        "sample_pack_claimed_as_condition_3",
        "local_only_called_public_evidence",
        "scaffold_sums_called_soak_evidence",
        "live_soak_pack_claimed",
        "pass_or_start_claimed",
    ):
        if not isinstance(block.get(key), bool):
            violations.append("public_evidence_pack")
    claims = block.get("refused_claims")
    expected_labels = [
        "sample_pack_called_condition_3",
        "local_only_called_public_evidence",
        "scaffold_sha256sums_called_soak_evidence",
        "sample_called_live_soak_pack",
    ]
    if not isinstance(claims, list):
        violations.append("public_evidence_pack")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if labels != expected_labels:
            violations.append("public_evidence_pack")
        else:
            flags = (
                "sample_pack_claimed_as_condition_3",
                "local_only_called_public_evidence",
                "scaffold_sums_called_soak_evidence",
                "live_soak_pack_claimed",
            )
            for item, flag in zip(claims, flags):
                if item.get(flag) is not True or item.get("condition_3_satisfied") is not False:
                    violations.append("condition_3_unsatisfied")
                if item.get("packs_live_soak_evidence") is not False:
                    violations.append("condition_3_unsatisfied")
                if item.get("local_only_counts_as_public_evidence") is not False:
                    violations.append("local_only_refused")
                if item.get("scaffold_sha256sums_is_soak_evidence") is not False:
                    violations.append("scaffold_sha256sums_not_soak_evidence")
                if item.get("l2_2_status") != "NOT_STARTED" or item.get("can_start_clock") is not False:
                    violations.append("offline_probe_is_not_a_start")
    detail = block.get("detail")
    ok = block.get("ok")
    passed_keys = (
        "classifies_or_validates_sample_public_pack_passed",
        "local_only_pack_rejected",
        "missing_piece_rejected",
        "scaffold_sha256sums_refused",
        "committed_scaffold_sums_refused",
        "implementation_present",
    )
    if require_success:
        if ok is not True or detail != SUCCESS_DETAIL or any(block.get(key) is not True for key in passed_keys):
            violations.append("public_evidence_pack")
        elif not samples_match(block.get("samples")):
            violations.append("public_evidence_pack")
    else:
        if detail not in FAILURE_DETAILS or not isinstance(ok, bool):
            violations.append("public_evidence_pack")
        elif ok is True and (
            detail != SUCCESS_DETAIL
            or any(block.get(key) is not True for key in passed_keys)
            or not samples_match(block.get("samples"))
        ):
            violations.append("public_evidence_pack")
        elif ok is not True and (
            any(block.get(key) is not False for key in passed_keys) or block.get("samples") not in ([], None)
        ):
            violations.append("public_evidence_pack")
    return violations


def _summary(validated: dict[str, Any]) -> dict[str, Any]:
    accepted = validated.get("accepted") is True
    body: dict[str, Any] = {
        "ok": True,
        "tool": TOOL,
        "action": ACTION,
        "dut": DUT,
        "hasher": HASHER,
        "accepted": accepted,
        "rejection": validated.get("rejection"),
        "missing": list(validated.get("missing") or []),
        "sample_only": validated.get("sample_only") is True,
        "offline": True,
        "classifies_or_validates_sample_public_pack_passed": accepted and validated.get("sample_only") is True,
        "local_only_pack_rejected": validated.get("rejection") == "local_only",
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
        "classifies_or_validates_sample_public_pack_passed": False,
        "local_only_pack_rejected": False,
        "note": NOTE,
    }
    body.update(_closed_flags())
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", default=None, help="JSON object to validate as a sample pack")
    parser.add_argument("--samples", action="store_true", help="validate the fixed sample set")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.samples:
        status = stable_scaffold_status()
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
        return 0 if status.get("ok") is True else 2
    if args.pack is None:
        print(json.dumps(_error_summary("pack_required"), ensure_ascii=False))
        return 2
    text = args.pack.strip()
    if not text.startswith("{"):
        print(json.dumps(_error_summary("pack_not_json"), ensure_ascii=False))
        return 2
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        print(json.dumps(_error_summary("pack_not_json"), ensure_ascii=False))
        return 2
    print(json.dumps(_summary(validate_pack(payload)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
