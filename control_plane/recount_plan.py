"""Apply a model-produced recount plan to appointment rows.

This module does not know the official T5 complaint answers and does not
supply default inclusion rules. Missing plan fields fail the revision.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


AMOUNT_PATHS_NOTE = "total_revenue, by_dept.*.revenue, by_month.*"
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _cents_to_two_decimal_string(cents: int) -> str:
    if isinstance(cents, bool) or not isinstance(cents, int) or cents < 0:
        raise ValueError("cents must be a non-negative integer")
    return f"{cents // 100}.{cents % 100:02d}"


def _cents_to_json_number(cents: int) -> int | float:
    if cents % 100 == 0:
        return cents // 100
    # Keep a JSON number whose decimal expansion matches the cents exactly.
    return json.loads(json.dumps(cents / 100.0))


def format_amount(cents: int, amount_format: str) -> Any:
    if amount_format == "two_decimal_string":
        return _cents_to_two_decimal_string(cents)
    if amount_format == "json_number":
        return _cents_to_json_number(cents)
    if amount_format == "leave_as_is":
        return _cents_to_json_number(cents)
    raise ValueError(f"unsupported amount_format: {amount_format}")


def _money_to_cents(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("amount is missing")
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        quantized = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return int(quantized * 100)
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"\d+\.\d{1,2}", text) and not re.fullmatch(r"\d+", text):
            raise ValueError(f"unrecognized amount string: {value}")
        quantized = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return int(quantized * 100)
    raise ValueError(f"unrecognized amount: {value!r}")


def _same_money(left: Any, right: Any) -> bool:
    try:
        return _money_to_cents(left) == _money_to_cents(right)
    except ValueError:
        return False


def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("recount_plan must be an object")
    statuses = plan.get("include_statuses")
    departments = plan.get("include_departments")
    amount_format = plan.get("amount_format")
    preserve = plan.get("preserve_paths")
    if not isinstance(statuses, list) or not statuses or not all(isinstance(s, str) and s for s in statuses):
        raise ValueError("recount_plan.include_statuses must be a non-empty list of strings")
    if not isinstance(departments, list) or not departments or not all(isinstance(s, str) and s for s in departments):
        raise ValueError("recount_plan.include_departments must be a non-empty list of strings")
    if amount_format not in {"two_decimal_string", "json_number", "leave_as_is"}:
        raise ValueError("recount_plan.amount_format is not supported")
    if preserve is None:
        preserve = []
    if not isinstance(preserve, list) or not all(isinstance(s, str) for s in preserve):
        raise ValueError("recount_plan.preserve_paths must be a list of strings")
    return {
        "include_statuses": list(statuses),
        "include_departments": list(departments),
        "amount_format": amount_format,
        "preserve_paths": list(preserve),
    }


def apply_recount(rows: list[dict], plan: dict, candidate_v3: dict) -> dict:
    plan = validate_plan(plan)
    statuses = set(plan["include_statuses"])
    included = [row for row in rows if row["status"] in statuses]

    total_cents = sum(row["fee_cents"] for row in included)
    by_dept_cents: dict[str, list[int]] = {dept: [0, 0] for dept in plan["include_departments"]}
    by_month_cents: dict[str, int] = defaultdict(int)
    for row in included:
        dept = row["dept"]
        if dept not in by_dept_cents:
            by_dept_cents[dept] = [0, 0]
        by_dept_cents[dept][0] += 1
        by_dept_cents[dept][1] += row["fee_cents"]
        month = row["visit_date"][:7]
        if not MONTH_RE.fullmatch(month):
            raise ValueError(f"bad visit_date: {row['visit_date']}")
        by_month_cents[month] += row["fee_cents"]

    amount_format = plan["amount_format"]
    candidate = {
        "total_revenue": format_amount(total_cents, amount_format),
        "by_dept": {},
        "by_month": {},
    }
    for dept in plan["include_departments"]:
        count, revenue = by_dept_cents[dept]
        candidate["by_dept"][dept] = {
            "count": count,
            "revenue": format_amount(revenue, amount_format),
        }
    for month in sorted(by_month_cents):
        candidate["by_month"][month] = format_amount(by_month_cents[month], amount_format)

    if "by_month" in plan["preserve_paths"]:
        original = candidate_v3.get("by_month")
        if not isinstance(original, dict) or not original:
            raise ValueError("candidate_v3.by_month is missing; cannot honor preserve_paths")
        preserved: dict[str, Any] = {}
        for month in sorted(original):
            value = original[month]
            if amount_format == "two_decimal_string":
                preserved[month] = _cents_to_two_decimal_string(_money_to_cents(value))
            elif amount_format == "leave_as_is":
                preserved[month] = value
            else:
                preserved[month] = _cents_to_json_number(_money_to_cents(value))
        candidate["by_month"] = preserved
    if "total_revenue" in plan["preserve_paths"]:
        candidate["total_revenue"] = candidate_v3["total_revenue"]
    return candidate


def months_preserved(candidate_v3: dict, candidate_v4: dict) -> bool:
    left = candidate_v3.get("by_month")
    right = candidate_v4.get("by_month")
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if set(left) != set(right):
        return False
    return all(_same_money(left[key], right[key]) for key in left)
