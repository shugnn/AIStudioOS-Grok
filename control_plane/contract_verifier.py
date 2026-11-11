"""Independent contract Verifier for the appointment summary.

Judges a candidate. Does not revise it, does not write candidate_v2, and does
not call a model API.

  PYTHONPATH=. python -m control_plane.contract_verifier \
      --candidate candidate.json --csv appts.csv --contract contract.json \
      --out verdict.json --step verify_v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from control_plane.appointment_rules import (
    MONTH_RE,
    aggregate,
    amount_to_cents,
    is_two_decimal_string,
    iter_amount_fields,
    load_appointments,
    load_contract,
    month_cents,
    sum_cents,
    validate_contract,
    write_json,
)


def _display(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _reason_r1(candidate: object) -> str | None:
    bad = [(path, value) for path, value in iter_amount_fields(candidate) if not is_two_decimal_string(value)]
    if not bad and not isinstance(candidate, dict):
        return 'Every amount must be a two-decimal string such as "1234.50", never a float. The candidate is not an object.'
    if not bad:
        return None
    shown = ", ".join(f"{path} ({type(value).__name__}: {_display(value)})" for path, value in bad)
    return (
        'Every amount must be a two-decimal string such as "1234.50", never a float. '
        f"Non-conforming: {shown}."
    )


def _reason_r2(candidate: object, contract: dict) -> str | None:
    required = list(contract["departments"])
    if not isinstance(candidate, dict) or not isinstance(candidate.get("by_dept"), dict):
        return (
            "by_dept must contain all four departments med/surg/ped/derm "
            "(include a department even if count is 0). by_dept is missing or not an object."
        )
    by_dept = candidate["by_dept"]
    problems: list[str] = []
    missing = [dept for dept in required if dept not in by_dept]
    extra = [dept for dept in by_dept if dept not in required]
    if missing:
        problems.append("missing " + ", ".join(missing))
    if extra:
        problems.append("unexpected " + ", ".join(extra))
    for dept in required:
        if dept not in by_dept:
            continue
        body = by_dept[dept]
        count = body.get("count") if isinstance(body, dict) else None
        if not isinstance(body, dict) or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            problems.append(f"{dept} count must be a non-negative integer")
    if not problems:
        return None
    return (
        "by_dept must contain all four departments med/surg/ped/derm "
        "(include a department even if count is 0). "
        + "; ".join(problems)
        + f". Found keys {list(by_dept)}."
    )


def _reason_r3(candidate: object) -> str | None:
    if not isinstance(candidate, dict) or not isinstance(candidate.get("by_month"), dict):
        return "by_month keys must be in ascending month order. by_month is missing or not an object."
    keys = list(candidate["by_month"])
    ascending = sorted(keys)
    invalid = [key for key in keys if MONTH_RE.fullmatch(str(key)) is None]
    if invalid or keys != ascending:
        return (
            "by_month keys must be in ascending month order. "
            f"Found {keys}. Ascending order is {ascending}."
        )
    return None


def _reason_r4(candidate: object, rows: list[dict], contract: dict) -> str | None:
    expected = aggregate(rows, contract)
    mismatches: list[str] = []
    actual_total = candidate.get("total_revenue") if isinstance(candidate, dict) else None
    actual_total_cents = amount_to_cents(actual_total)
    expected_total_cents = amount_to_cents(expected["total_revenue"])
    if actual_total_cents != expected_total_cents:
        mismatches.append(
            f"total_revenue is {_display(actual_total)} but completed fee_cents sum to {expected['total_revenue']}"
        )
        all_cents = sum_cents(rows, status=None)
        if actual_total_cents == all_cents and all_cents != expected_total_cents:
            mismatches.append(
                "total_revenue equals fee_cents summed over every status, including cancelled and no_show"
            )

    by_dept = candidate.get("by_dept") if isinstance(candidate, dict) and isinstance(candidate.get("by_dept"), dict) else {}
    for dept in contract["departments"]:
        exp = expected["by_dept"][dept]
        exp_cents = amount_to_cents(exp["revenue"])
        if dept not in by_dept:
            if exp["count"] or exp_cents:
                mismatches.append(
                    f"by_dept.{dept} is absent so its {exp['count']} completed row(s) "
                    f"({exp['revenue']}) are not counted"
                )
            continue
        body = by_dept[dept] if isinstance(by_dept[dept], dict) else {}
        got_count = body.get("count")
        got_revenue = body.get("revenue")
        if got_count != exp["count"] or amount_to_cents(got_revenue) != exp_cents:
            mismatches.append(
                f"by_dept.{dept} count/revenue is {got_count}/{_display(got_revenue)} "
                f"but completed rows are {exp['count']}/{exp['revenue']}"
            )

    by_month = candidate.get("by_month") if isinstance(candidate, dict) and isinstance(candidate.get("by_month"), dict) else None
    if by_month is None:
        mismatches.append("by_month is missing or not an object")
    else:
        expected_months = month_cents(rows, status=contract["count_status"])
        parsed: dict[str, int] = {}
        parse_ok = True
        for key, value in by_month.items():
            cents = amount_to_cents(value)
            if cents is None:
                parse_ok = False
                break
            parsed[str(key)] = cents
        if not parse_ok or parsed != expected_months:
            mismatches.append("by_month revenue does not equal status=completed rows grouped by YYYY-MM")
            all_months = month_cents(rows, status=None)
            if parse_ok and parsed == all_months and parsed != expected_months:
                mismatches.append("by_month revenue matches every status, including cancelled and no_show")

    if not mismatches:
        return None
    return "Only status=completed rows count toward counts and revenue. " + ". ".join(mismatches) + "."


def judge(candidate: object, rows: list[dict], contract: dict) -> dict:
    """Return the public verdict object and nothing else."""
    contract = validate_contract(dict(contract))
    reasons = []
    for rule, detail in (
        ("R1", _reason_r1(candidate)),
        ("R2", _reason_r2(candidate, contract)),
        ("R3", _reason_r3(candidate)),
        ("R4", _reason_r4(candidate, rows, contract)),
    ):
        if detail:
            reasons.append({"rule": rule, "detail": detail})
    if reasons:
        return {"verdict": "REJECTED", "reasons": reasons}
    return {"verdict": "ACCEPTED", "checks": len(contract["rules"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge an appointment summary against the frozen contract.")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--step", required=True)
    args = parser.parse_args(argv)
    try:
        candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
        rows = load_appointments(Path(args.csv))
        contract = load_contract(Path(args.contract))
        verdict = judge(candidate, rows, contract)
        out = Path(args.out)
        write_json(out, verdict)
    except Exception as exc:  # noqa: BLE001 — CLI boundary reports the failure as JSON
        print(
            json.dumps(
                {
                    "ok": False,
                    "role": "verifier",
                    "step": args.step,
                    "pid": os.getpid(),
                    "error": str(exc),
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "role": "verifier",
                "step": args.step,
                "pid": os.getpid(),
                "verdict": verdict["verdict"],
                "wrote": [str(Path(args.out).resolve())],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
