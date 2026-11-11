"""Worker for DS-T4-20261112. Invoked only as a step of scripts/worker_run_task.py.

prepare_input writes appts.csv from the published generator and fails if the
written bytes do not match the frozen fingerprint.

revise reads the Verifier's verdict_v1.json and rewrites the candidate from
appts.csv. It does not write verdict files and does not call a model API.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from control_plane.appointment_rules import (
    aggregate,
    is_two_decimal_string,
    iter_amount_fields,
    load_appointments,
    load_contract,
    write_json,
)

# Frozen by Issue #9 comments 6802795658 and 6804695605.
# Do not hand-edit appts.csv to force these.
EXPECTED_SHA256 = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"
EXPECTED_BYTES = 12350
EXPECTED_NEWLINES = 301


def _render_csv(generator_path: Path) -> str:
    source = generator_path.read_bytes()
    if source.startswith(b"\xef\xbb\xbf"):
        raise ValueError("generator has a BOM")
    namespace: dict = {"__name__": "generate_appts"}
    exec(compile(source.decode("utf-8"), str(generator_path), "exec"), namespace)
    csv_text = namespace.get("csv")
    if not isinstance(csv_text, str):
        raise ValueError("generator did not produce csv text")
    return csv_text


def prepare_input(*, inbox: Path) -> dict:
    generator = inbox / "generate_appts.py"
    csv_text = _render_csv(generator)
    data = csv_text.encode("utf-8")
    path = inbox / "data" / "appts.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    written = path.read_bytes()
    digest = hashlib.sha256(written).hexdigest()
    newlines = written.count(b"\n")
    match = (
        written == data
        and digest == EXPECTED_SHA256
        and len(written) == EXPECTED_BYTES
        and newlines == EXPECTED_NEWLINES
        and written.endswith(b"\n")
        and not written.startswith(b"\xef\xbb\xbf")
        and b"\r" not in written
    )
    return {
        "ok": match,
        "sha256": digest,
        "bytes": len(written),
        "lines": newlines,
        "expected_sha256": EXPECTED_SHA256,
        "expected_bytes": EXPECTED_BYTES,
        "match": match,
        "wrote": ["data/appts.csv"],
        "error": None if match else "fingerprint_mismatch",
    }


def _display(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    return str(value)


def _change_text(rule: str, candidate_v1: dict, candidate_v2: dict, contract: dict) -> tuple[bool, str]:
    if rule == "R1":
        before = [path for path, value in iter_amount_fields(candidate_v1) if not is_two_decimal_string(value)]
        after = [path for path, value in iter_amount_fields(candidate_v2) if is_two_decimal_string(value)]
        return True, (
            f"Addressed R1: {len(before)} amount field(s) in the rejected candidate were not two-decimal strings. "
            f"candidate_v2 writes {len(after)} amount field(s) as two-decimal strings, formatted from integer fee_cents."
        )
    if rule == "R2":
        required = list(contract["departments"])
        found = list(candidate_v1.get("by_dept", {})) if isinstance(candidate_v1.get("by_dept"), dict) else []
        missing = [dept for dept in required if dept not in found]
        return True, (
            f"Addressed R2: by_dept keys were {found}. Missing departments {missing} are present in candidate_v2. "
            f"by_dept now contains {required}."
        )
    if rule == "R3":
        before = list(candidate_v1.get("by_month", {})) if isinstance(candidate_v1.get("by_month"), dict) else []
        after = list(candidate_v2.get("by_month", {}))
        return True, (
            f"Addressed R3: by_month key order was {before}. candidate_v2 key order is ascending: {after}."
        )
    if rule == "R4":
        return True, (
            "Addressed R4: counts and revenue were recomputed from appts.csv. "
            "Only rows with status=completed are included. cancelled and no_show rows contribute nothing. "
            f"total_revenue changed from {_display(candidate_v1.get('total_revenue'))} "
            f"to {candidate_v2['total_revenue']}. by_dept counts and revenue, and by_month revenue, "
            "were rewritten from those completed fee_cents."
        )
    return False, f"No revision rule is implemented for {rule}."


def revise(*, inbox: Path, task_id: str) -> dict:
    out = inbox / "deliverables"
    verdict_path = out / "verdict_v1.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    if verdict.get("verdict") != "REJECTED":
        return {"ok": False, "error": "revise_requires_rejected_verdict", "wrote": []}
    reasons = verdict.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        return {"ok": False, "error": "verdict_has_no_reasons", "wrote": []}

    contract = load_contract(inbox / "contract.json")
    rows = load_appointments(inbox / "data" / "appts.csv")
    candidate_v2 = aggregate(rows, contract)
    candidate_v1 = json.loads((inbox / "candidate_v1.json").read_text(encoding="utf-8"))
    if not isinstance(candidate_v1, dict):
        candidate_v1 = {}

    entries = []
    ok = True
    for reason in reasons:
        rule = reason.get("rule")
        detail = reason.get("detail")
        if not isinstance(rule, str) or not isinstance(detail, str):
            ok = False
            entries.append(
                {
                    "rule": rule if isinstance(rule, str) else "",
                    "reason": detail if isinstance(detail, str) else "",
                    "addressed": False,
                    "change": "Reason was missing a rule id or detail, so it was not addressed.",
                }
            )
            continue
        addressed, change = _change_text(rule, candidate_v1, candidate_v2, contract)
        ok = ok and addressed
        entries.append(
            {
                "rule": rule,
                "reason": detail,
                "addressed": addressed,
                "change": change,
            }
        )

    write_json(out / "candidate_v2.json", candidate_v2)
    write_json(
        out / "revision_log.json",
        {"task_id": task_id, "entries": entries},
    )
    return {
        "ok": ok,
        "wrote": ["deliverables/candidate_v2.json", "deliverables/revision_log.json"],
        "error": None if ok else "unaddressed_reason",
    }
