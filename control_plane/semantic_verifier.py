"""Product Verifier for DS-T5-20261112.

This process writes verdict.json only. It does not call a model API and it
does not write interpretation, candidate, or usage files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

from control_plane.appointment_rules import load_appointments
from control_plane.recount_plan import apply_recount, months_preserved, validate_plan

EXPECTED_SHA256 = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"
EXPECTED_BYTES = 12350
EXPECTED_NEWLINES = 301
CAP_CNY = Decimal("5.00")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def verify(inbox: Path) -> dict:
    checks: list[dict] = []
    csv_path = inbox / "data" / "appts.csv"
    data = csv_path.read_bytes() if csv_path.is_file() else b""
    digest = hashlib.sha256(data).hexdigest() if data else ""
    fp_ok = (
        csv_path.is_file()
        and digest == EXPECTED_SHA256
        and len(data) == EXPECTED_BYTES
        and data.count(b"\n") == EXPECTED_NEWLINES
    )
    checks.append(_check("A-1_fingerprint", fp_ok, f"sha256={digest} bytes={len(data)} lines={data.count(b'\n')}"))

    interpretation_path = inbox / "deliverables" / "interpretation.json"
    try:
        items = json.loads(interpretation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        items = None
    interp_ok = (
        isinstance(items, list)
        and len(items) == 4
        and all(
            isinstance(item, dict)
            and item.get("complaint") == index
            and isinstance(item.get("understood_as"), str)
            and item["understood_as"].strip()
            and isinstance(item.get("target_path"), str)
            and item["target_path"].strip()
            and isinstance(item.get("fix"), str)
            and item["fix"].strip()
            for index, item in enumerate(items or [], start=1)
        )
    )
    checks.append(_check("A-4_interpretation", interp_ok, "interpretation.json must have 4 complaint items with required fields"))

    usage_path = inbox / "deliverables" / "model_usage.json"
    try:
        usage = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        usage = {}
    try:
        estimated = Decimal(str(usage.get("estimated_cny_exact") or usage.get("estimated_cny") or "nan"))
    except Exception:
        estimated = Decimal("NaN")
    usage_ok = (
        isinstance(usage, dict)
        and usage.get("step") == "interpret_complaint"
        and int(usage.get("calls") or 0) >= 1
        and int(usage.get("prompt_tokens") or 0) > 0
        and int(usage.get("completion_tokens") or 0) > 0
        and estimated == estimated
        and estimated <= CAP_CNY
    )
    checks.append(
        _check(
            "A-2_model_usage",
            usage_ok,
            f"step={usage.get('step')} calls={usage.get('calls')} "
            f"prompt_tokens={usage.get('prompt_tokens')} completion_tokens={usage.get('completion_tokens')} "
            f"estimated_cny={usage.get('estimated_cny')}",
        )
    )
    checks.append(
        _check(
            "A-6_cost_cap",
            estimated == estimated and estimated <= CAP_CNY,
            f"estimated_cny={usage.get('estimated_cny')} cap={CAP_CNY}",
        )
    )

    plan_path = inbox / "deliverables" / "recount_plan.json"
    candidate_path = inbox / "deliverables" / "candidate_v4.json"
    v3_path = inbox / "candidate_v3.json"
    try:
        plan = validate_plan(json.loads(plan_path.read_text(encoding="utf-8")))
        candidate_v4 = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate_v3 = json.loads(v3_path.read_text(encoding="utf-8"))
        rows = load_appointments(csv_path)
        expected = apply_recount(rows, plan, candidate_v3)
        consistent = candidate_v4 == expected
        month_ok = True
        month_detail = "by_month not in preserve_paths"
        if "by_month" in plan["preserve_paths"]:
            month_ok = months_preserved(candidate_v3, candidate_v4)
            month_detail = "by_month values preserved from candidate_v3 (format may be normalized)"
    except Exception as exc:  # noqa: BLE001 — verifier records the failure
        plan = None
        consistent = False
        month_ok = False
        month_detail = str(exc)
    checks.append(_check("A-3_candidate_matches_plan", consistent, "candidate_v4 must match a deterministic apply of the model recount_plan"))
    checks.append(_check("A-3_months_untouched_if_preserved", month_ok, month_detail))

    accepted = all(item["ok"] for item in checks)
    return {
        "verdict": "ACCEPTED" if accepted else "REJECTED",
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--step", default="verify")
    args = parser.parse_args(argv)
    inbox = Path(args.inbox).resolve()
    out = Path(args.out).resolve()
    try:
        verdict = verify(inbox)
        ok = True
        error = None
    except Exception as exc:  # noqa: BLE001 — child process boundary
        verdict = {"verdict": "REJECTED", "checks": [], "error": str(exc)}
        ok = False
        error = str(exc)
    _write_json(out, verdict)
    payload = {
        "ok": ok and verdict.get("verdict") in {"ACCEPTED", "REJECTED"},
        "role": "verifier",
        "step": args.step,
        "pid": os.getpid(),
        "verdict": verdict.get("verdict"),
        "wrote": [str(out)],
        "error": error,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
