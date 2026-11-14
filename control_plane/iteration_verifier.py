"""Product Verifier for DS-T6-20261114. Scores R1-R5 only.

This process does not call a model API and does not write plans or candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from control_plane.appointment_rules import (
    amount_to_cents,
    is_two_decimal_string,
    iter_amount_fields,
    load_appointments,
)

EXPECTED_SHA256 = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"
EXPECTED_BYTES = 12350
EXPECTED_NEWLINES = 301
REQUIRED_DEPARTMENTS = ("med", "surg", "ped", "derm")
RULES = ("R1", "R2", "R3", "R4", "R5")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def input_fingerprint(csv_path: Path) -> dict:
    data = csv_path.read_bytes() if csv_path.is_file() else b""
    digest = hashlib.sha256(data).hexdigest() if data else ""
    lines = data.count(b"\n")
    ok = (
        csv_path.is_file()
        and digest == EXPECTED_SHA256
        and len(data) == EXPECTED_BYTES
        and lines == EXPECTED_NEWLINES
    )
    return {
        "ok": ok,
        "sha256": digest,
        "bytes": len(data),
        "lines": lines,
        "expected_sha256": EXPECTED_SHA256,
        "expected_bytes": EXPECTED_BYTES,
        "expected_lines": EXPECTED_NEWLINES,
    }


def score_candidate(candidate: dict, rows: list[dict], input_sha256: str) -> dict:
    checks = {
        "R1": _score_r1(candidate),
        "R2": _score_r2(candidate),
        "R3": _score_r3(candidate, rows),
        "R4": _score_r4(candidate, rows),
        "R5": _score_r5(candidate, input_sha256),
    }
    passed = sum(1 for rule in RULES if checks[rule]["pass"])
    return {
        "score": f"{passed}/5",
        "passed": passed,
        "total": 5,
        "checks": checks,
        "input_sha256": input_sha256,
        "failing": [rule for rule in RULES if not checks[rule]["pass"]],
        "passing": [rule for rule in RULES if checks[rule]["pass"]],
    }


def _score_r1(candidate: dict) -> dict:
    bad = []
    for path, value in iter_amount_fields(candidate):
        if not is_two_decimal_string(value):
            bad.append((path, value, type(value).__name__))
    if bad:
        return {"pass": False, "reason": f"non-compliant amounts: {bad}"}
    return {"pass": True, "reason": "all amounts are two-decimal strings"}


def _score_r2(candidate: dict) -> dict:
    by_dept = candidate.get("by_dept")
    keys = sorted(by_dept) if isinstance(by_dept, dict) else []
    missing = [dept for dept in REQUIRED_DEPARTMENTS if dept not in keys]
    if missing:
        return {
            "pass": False,
            "reason": f"by_dept keys={keys}; required={list(REQUIRED_DEPARTMENTS)}; missing={missing}",
        }
    return {"pass": True, "reason": f"by_dept contains {list(REQUIRED_DEPARTMENTS)}"}


def _score_r3(candidate: dict, rows: list[dict]) -> dict:
    by_month = candidate.get("by_month")
    keys = list(by_month) if isinstance(by_month, dict) else []
    data_months = sorted({str(row["visit_date"])[:7] for row in rows})
    ascending = keys == sorted(keys)
    missing = [month for month in data_months if month not in keys]
    if not ascending or missing:
        return {
            "pass": False,
            "reason": (
                f"by_month keys={keys}; data months={data_months}; "
                f"ascending={ascending}; missing={missing}"
            ),
        }
    return {
        "pass": True,
        "reason": f"by_month keys={keys}; data months={data_months}; ascending=True",
    }


def _score_r4(candidate: dict, rows: list[dict]) -> dict:
    completed = [row for row in rows if row["status"] == "completed"]
    expected_total = sum(row["fee_cents"] for row in completed)
    expected_dept: dict[str, list[int]] = {}
    expected_month: dict[str, int] = {}
    for row in completed:
        bucket = expected_dept.setdefault(row["dept"], [0, 0])
        bucket[0] += 1
        bucket[1] += row["fee_cents"]
        month = str(row["visit_date"])[:7]
        expected_month[month] = expected_month.get(month, 0) + row["fee_cents"]
    problems: list[str] = []
    got_total = amount_to_cents(candidate.get("total_revenue"))
    if got_total != expected_total:
        problems.append(f"total_revenue {got_total} != completed-only {expected_total}")
    by_dept = candidate.get("by_dept")
    if isinstance(by_dept, dict):
        for dept, body in by_dept.items():
            expected_count, expected_cents = expected_dept.get(dept, [0, 0])
            got_count = body.get("count") if isinstance(body, dict) else None
            got_cents = amount_to_cents(body.get("revenue") if isinstance(body, dict) else None)
            if got_count != expected_count:
                problems.append(f"by_dept.{dept}.count {got_count} != {expected_count}")
            if got_cents != expected_cents:
                problems.append(f"by_dept.{dept}.revenue cents {got_cents} != {expected_cents}")
    by_month = candidate.get("by_month")
    if isinstance(by_month, dict):
        for month, value in by_month.items():
            got = amount_to_cents(value)
            expected = expected_month.get(month, 0)
            if got != expected:
                problems.append(f"by_month.{month} cents {got} != completed-only {expected}")
    if problems:
        return {"pass": False, "reason": "; ".join(problems)}
    return {"pass": True, "reason": "present count and revenue fields use status=completed only"}


def _score_r5(candidate: dict, input_sha256: str) -> dict:
    value = candidate.get("generated_from") if isinstance(candidate, dict) else None
    if value != input_sha256:
        return {"pass": False, "reason": f"generated_from={value!r}; expected={input_sha256}"}
    return {"pass": True, "reason": "generated_from equals the input SHA256"}


def verify(inbox: Path, round_no: int, final: bool = False) -> dict:
    csv_path = inbox / "data" / "appts.csv"
    fingerprint = input_fingerprint(csv_path)
    if not fingerprint["ok"]:
        raise ValueError(f"fingerprint_mismatch: {fingerprint}")
    candidate_path = inbox / "deliverables" / "current_candidate.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    rows = load_appointments(csv_path)
    result = score_candidate(candidate, rows, fingerprint["sha256"])
    result["task_id"] = "DS-T6-20261114"
    result["round"] = round_no
    result["paid_api_called"] = False
    result["model_called"] = False
    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "current_score.json", result)
    if round_no <= 0:
        _write_json(out / "initial_score.json", result)
    else:
        round_dir = out / "rounds" / f"{round_no:02d}"
        _write_json(round_dir / "score.json", result)
    if final:
        _write_json(
            out / "verifier_final.json",
            {
                "task_id": "DS-T6-20261114",
                "score": result["score"],
                "checks": result["checks"],
                "input_sha256": result["input_sha256"],
                "round": round_no,
                "note": (
                    "Product-side score of final_candidate / current_candidate. "
                    "Not observation-track acceptance."
                ),
            },
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--step", default="score")
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args(argv)
    inbox = Path(args.inbox).resolve()
    try:
        result = verify(inbox, args.round, final=args.final)
        ok = True
        error = None
    except Exception as exc:  # noqa: BLE001 — child process boundary
        result = {"score": None, "error": str(exc)}
        ok = False
        error = str(exc)
    wrote = ["deliverables/current_score.json"]
    if args.round <= 0:
        wrote.append("deliverables/initial_score.json")
    else:
        wrote.append(f"deliverables/rounds/{args.round:02d}/score.json")
    if args.final:
        wrote.append("deliverables/verifier_final.json")
    payload = {
        "ok": ok,
        "role": "verifier",
        "step": args.step,
        "pid": os.getpid(),
        "round": args.round,
        "score": result.get("score"),
        "passed": result.get("passed"),
        "failing": result.get("failing"),
        "wrote": wrote,
        "error": error,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
