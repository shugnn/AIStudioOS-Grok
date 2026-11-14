"""Apply one single-rule iteration patch at a time.

The applicator does not choose which rule to fix and does not call a model.
It refuses a plan that names more than one rule or whose op does not match
the targeted rule. Amount formatting of existing fields is preserved unless
the targeted rule is R1.
"""

from __future__ import annotations

import copy
from typing import Any

from control_plane.appointment_rules import (
    amount_to_cents,
    cents_to_money,
    is_two_decimal_string,
    iter_amount_fields,
)
from control_plane.recount_plan import format_amount

RULE_OPS = {
    "R1": "format_amounts",
    "R2": "ensure_departments",
    "R3": "ensure_months",
    "R4": "filter_statuses",
    "R5": "set_generated_from",
}
REQUIRED_DEPARTMENTS = ("med", "surg", "ped", "derm")
REASONING_LIMIT = 120


def infer_amount_format(candidate: dict) -> str:
    values = [value for _, value in iter_amount_fields(candidate)]
    if values and all(is_two_decimal_string(value) for value in values):
        return "two_decimal_string"
    return "json_number"


def format_like(cents: int, existing: object, fallback: str) -> Any:
    if is_two_decimal_string(existing):
        return cents_to_money(cents)
    return format_amount(cents, fallback)


def clip_reasoning(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= REASONING_LIMIT:
        return cleaned
    return cleaned[:REASONING_LIMIT]


def validate_iteration_plan(plan: object) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("iteration plan must be an object")
    rule = plan.get("rule_targeted")
    if rule not in RULE_OPS:
        raise ValueError(f"rule_targeted must be one of {sorted(RULE_OPS)}")
    reasoning = plan.get("model_reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("model_reasoning must be a non-empty string")
    patch = plan.get("patch")
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    extra_ops = [key for key in plan if key not in {"rule_targeted", "model_reasoning", "patch"}]
    if extra_ops:
        # Tolerate unused bookkeeping keys but reject a second patch/plan.
        if "patches" in plan or "recount_plan" in plan or "extra_patch" in plan:
            raise ValueError("iteration plan must contain exactly one patch")
    op = patch.get("op")
    expected = RULE_OPS[rule]
    if op != expected:
        raise ValueError(f"patch.op for {rule} must be {expected}")
    cleaned_patch = {"op": op}
    if op == "format_amounts":
        amount_format = patch.get("amount_format", "two_decimal_string")
        if amount_format != "two_decimal_string":
            raise ValueError("R1 amount_format must be two_decimal_string")
        cleaned_patch["amount_format"] = "two_decimal_string"
    elif op == "ensure_departments":
        departments = patch.get("departments")
        statuses = patch.get("include_statuses")
        if not isinstance(departments, list) or not departments or not all(isinstance(item, str) and item for item in departments):
            raise ValueError("ensure_departments.departments must be a non-empty list of strings")
        if not isinstance(statuses, list) or not statuses or not all(isinstance(item, str) and item for item in statuses):
            raise ValueError("ensure_departments.include_statuses must be a non-empty list of strings")
        cleaned_patch["departments"] = list(departments)
        cleaned_patch["include_statuses"] = list(statuses)
    elif op == "ensure_months":
        statuses = patch.get("include_statuses")
        if not isinstance(statuses, list) or not statuses or not all(isinstance(item, str) and item for item in statuses):
            raise ValueError("ensure_months.include_statuses must be a non-empty list of strings")
        cleaned_patch["include_statuses"] = list(statuses)
    elif op == "filter_statuses":
        statuses = patch.get("include_statuses")
        if not isinstance(statuses, list) or not statuses or not all(isinstance(item, str) and item for item in statuses):
            raise ValueError("filter_statuses.include_statuses must be a non-empty list of strings")
        cleaned_patch["include_statuses"] = list(statuses)
    elif op == "set_generated_from":
        value = patch.get("value")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("set_generated_from.value must be a non-empty string")
        cleaned_patch["value"] = value.strip()
    return {
        "rule_targeted": rule,
        "model_reasoning": clip_reasoning(reasoning),
        "model_reasoning_full": reasoning.strip(),
        "patch": cleaned_patch,
    }


def apply_iteration_plan(candidate: dict, rows: list[dict], plan: dict, input_sha256: str) -> dict:
    plan = validate_iteration_plan(plan)
    current = copy.deepcopy(candidate)
    if not isinstance(current, dict):
        raise ValueError("candidate must be an object")
    op = plan["patch"]["op"]
    if op == "format_amounts":
        return _apply_format_amounts(current)
    if op == "ensure_departments":
        return _apply_ensure_departments(current, rows, plan["patch"])
    if op == "ensure_months":
        return _apply_ensure_months(current, rows, plan["patch"])
    if op == "filter_statuses":
        return _apply_filter_statuses(current, rows, plan["patch"])
    if op == "set_generated_from":
        return _apply_generated_from(current, plan["patch"], input_sha256)
    raise ValueError(f"unsupported op: {op}")


def _apply_format_amounts(candidate: dict) -> dict:
    total = candidate.get("total_revenue")
    cents = amount_to_cents(total)
    if cents is None:
        raise ValueError("total_revenue cannot be formatted as a two-decimal string")
    candidate["total_revenue"] = cents_to_money(cents)
    by_dept = candidate.get("by_dept")
    if isinstance(by_dept, dict):
        for body in by_dept.values():
            if not isinstance(body, dict):
                raise ValueError("by_dept entry is not an object")
            revenue = amount_to_cents(body.get("revenue"))
            if revenue is None:
                raise ValueError("department revenue cannot be formatted as a two-decimal string")
            body["revenue"] = cents_to_money(revenue)
    by_month = candidate.get("by_month")
    if isinstance(by_month, dict):
        for month, value in list(by_month.items()):
            revenue = amount_to_cents(value)
            if revenue is None:
                raise ValueError(f"by_month.{month} cannot be formatted as a two-decimal string")
            by_month[month] = cents_to_money(revenue)
    return candidate


def _apply_ensure_departments(candidate: dict, rows: list[dict], patch: dict) -> dict:
    fallback = infer_amount_format(candidate)
    statuses = set(patch["include_statuses"])
    by_dept = candidate.setdefault("by_dept", {})
    if not isinstance(by_dept, dict):
        raise ValueError("by_dept must be an object")
    totals: dict[str, list[int]] = {}
    for row in rows:
        if row["status"] not in statuses:
            continue
        dept = row["dept"]
        bucket = totals.setdefault(dept, [0, 0])
        bucket[0] += 1
        bucket[1] += row["fee_cents"]
    for dept in patch["departments"]:
        if dept in by_dept:
            continue
        count, cents = totals.get(dept, [0, 0])
        by_dept[dept] = {"count": count, "revenue": format_amount(cents, fallback)}
    return candidate


def _apply_ensure_months(candidate: dict, rows: list[dict], patch: dict) -> dict:
    fallback = infer_amount_format(candidate)
    statuses = set(patch["include_statuses"])
    data_months = sorted({str(row["visit_date"])[:7] for row in rows})
    by_month = candidate.get("by_month")
    if not isinstance(by_month, dict):
        by_month = {}
        candidate["by_month"] = by_month
    month_cents: dict[str, int] = {}
    for row in rows:
        if row["status"] not in statuses:
            continue
        month = str(row["visit_date"])[:7]
        month_cents[month] = month_cents.get(month, 0) + row["fee_cents"]
    for month in data_months:
        if month not in by_month:
            by_month[month] = format_amount(month_cents.get(month, 0), fallback)
    candidate["by_month"] = {month: by_month[month] for month in sorted(by_month)}
    return candidate


def _apply_filter_statuses(candidate: dict, rows: list[dict], patch: dict) -> dict:
    fallback = infer_amount_format(candidate)
    statuses = set(patch["include_statuses"])
    included = [row for row in rows if row["status"] in statuses]
    total = sum(row["fee_cents"] for row in included)
    candidate["total_revenue"] = format_like(total, candidate.get("total_revenue"), fallback)
    by_dept = candidate.get("by_dept")
    if isinstance(by_dept, dict):
        dept_totals: dict[str, list[int]] = {dept: [0, 0] for dept in by_dept}
        for row in included:
            dept = row["dept"]
            if dept not in dept_totals:
                continue
            dept_totals[dept][0] += 1
            dept_totals[dept][1] += row["fee_cents"]
        for dept, body in by_dept.items():
            if not isinstance(body, dict):
                raise ValueError("by_dept entry is not an object")
            count, cents = dept_totals[dept]
            body["count"] = count
            body["revenue"] = format_like(cents, body.get("revenue"), fallback)
    by_month = candidate.get("by_month")
    if isinstance(by_month, dict):
        month_totals = {month: 0 for month in by_month}
        for row in included:
            month = str(row["visit_date"])[:7]
            if month in month_totals:
                month_totals[month] += row["fee_cents"]
        for month, existing in list(by_month.items()):
            by_month[month] = format_like(month_totals[month], existing, fallback)
    return candidate


def _apply_generated_from(candidate: dict, patch: dict, input_sha256: str) -> dict:
    value = patch["value"]
    if value == "input_sha256":
        value = input_sha256
    candidate["generated_from"] = value
    return candidate
