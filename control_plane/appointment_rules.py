"""Frozen appointment-summary rules for DS-T4-20261112.

Pure calculations only. This module does not write verdict files and does not
revise a candidate. The Verifier and the Worker both call it so the frozen
rule has one implementation; they still run as separate steps.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

RULE_IDS = ("R1", "R2", "R3", "R4")
DEPARTMENTS = ("med", "surg", "ped", "derm")
COUNT_STATUS = "completed"
AMOUNT_RE = re.compile(r"\d+\.\d{2}")
MONTH_RE = re.compile(r"\d{4}-\d{2}")


def validate_contract(contract: dict) -> dict:
    if list(contract.get("rules", {})) != list(RULE_IDS):
        raise ValueError("contract rules must be exactly R1, R2, R3, R4")
    if list(contract.get("departments", [])) != list(DEPARTMENTS):
        raise ValueError("departments must be med, surg, ped, derm in that order")
    if contract.get("count_status") != COUNT_STATUS:
        raise ValueError("count_status must be completed")
    return contract


def load_contract(path: Path) -> dict:
    return validate_contract(json.loads(path.read_text(encoding="utf-8")))


def load_appointments(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["appt_id", "patient_id", "dept", "visit_date", "fee_cents", "status"]
        if reader.fieldnames != expected:
            raise ValueError(f"unexpected header: {reader.fieldnames}")
        for raw in reader:
            fee = int(raw["fee_cents"])
            if fee < 0:
                raise ValueError("fee_cents must be non-negative")
            rows.append(
                {
                    "appt_id": raw["appt_id"],
                    "patient_id": raw["patient_id"],
                    "dept": raw["dept"],
                    "visit_date": raw["visit_date"],
                    "fee_cents": fee,
                    "status": raw["status"],
                }
            )
    return rows


def cents_to_money(cents: int) -> str:
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        raise ValueError("cents must be a non-negative integer")
    return f"{cents // 100}.{cents % 100:02d}"


def is_two_decimal_string(value: object) -> bool:
    return isinstance(value, str) and AMOUNT_RE.fullmatch(value) is not None


def amount_to_cents(value: object) -> int | None:
    """Parse an amount without binary float arithmetic.

    Strings must already be two-decimal. JSON numbers are read back through
    their JSON literal so a value such as 18093.9 becomes 1809390 cents.
    """
    if isinstance(value, str):
        if not is_two_decimal_string(value):
            return None
        whole, frac = value.split(".")
        return int(whole) * 100 + int(frac)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    literal = json.dumps(value)
    if not re.fullmatch(r"\d+(?:\.\d+)?", literal):
        return None
    from decimal import Decimal, ROUND_HALF_UP

    quantized = (Decimal(literal) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def iter_amount_fields(candidate: object):
    if not isinstance(candidate, dict):
        return
    yield "total_revenue", candidate.get("total_revenue")
    by_dept = candidate.get("by_dept")
    if isinstance(by_dept, dict):
        for dept, body in by_dept.items():
            revenue = body.get("revenue") if isinstance(body, dict) else None
            yield f"by_dept.{dept}.revenue", revenue
    by_month = candidate.get("by_month")
    if isinstance(by_month, dict):
        for month, value in by_month.items():
            yield f"by_month.{month}", value


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def aggregate(rows: list[dict], contract: dict) -> dict:
    """Summarize status=completed rows. Amounts are two-decimal strings.

    Every contract department is present. A department with no completed rows
    has count 0 and revenue 0.00. Months appear only when they have at least
    one completed row, and their keys are ascending.
    """
    validate_contract(contract)
    departments = list(contract["departments"])
    status = contract["count_status"]
    dept_count = {dept: 0 for dept in departments}
    dept_cents = {dept: 0 for dept in departments}
    month_cents: dict[str, int] = {}
    total = 0
    for row in rows:
        if row["status"] != status:
            continue
        dept = row["dept"]
        if dept not in dept_cents:
            raise ValueError(f"completed row has department outside the contract: {dept}")
        fee = row["fee_cents"]
        if isinstance(fee, bool) or not isinstance(fee, int) or fee < 0:
            raise ValueError("fee_cents must be a non-negative integer")
        month = str(row["visit_date"])[:7]
        if MONTH_RE.fullmatch(month) is None:
            raise ValueError(f"visit_date is not YYYY-MM-DD: {row['visit_date']}")
        dept_count[dept] += 1
        dept_cents[dept] += fee
        month_cents[month] = month_cents.get(month, 0) + fee
        total += fee
    return {
        "total_revenue": cents_to_money(total),
        "by_dept": {
            dept: {"count": dept_count[dept], "revenue": cents_to_money(dept_cents[dept])}
            for dept in departments
        },
        "by_month": {month: cents_to_money(month_cents[month]) for month in sorted(month_cents)},
    }


def sum_cents(rows: list[dict], status: str | None = None) -> int:
    total = 0
    for row in rows:
        if status is not None and row["status"] != status:
            continue
        total += int(row["fee_cents"])
    return total


def month_cents(rows: list[dict], status: str | None = None) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in rows:
        if status is not None and row["status"] != status:
            continue
        month = str(row["visit_date"])[:7]
        totals[month] = totals.get(month, 0) + int(row["fee_cents"])
    return totals


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
