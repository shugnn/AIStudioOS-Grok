"""Worker for DS-T5-20261112. Invoked only as a step of scripts/worker_run_task.py.

The Worker does not write verdict files. It must call a model to interpret the
natural-language complaints and must not hand-translate those complaints into
frozen rules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from control_plane.appointment_rules import load_appointments
from control_plane.deepseek_client import chat_json
from control_plane.recount_plan import apply_recount, validate_plan

EXPECTED_SHA256 = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"
EXPECTED_BYTES = 12350
EXPECTED_NEWLINES = 301
CAP_CNY = 5.00
MODEL = "deepseek-flash"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "ok": (
            hashlib.sha256(data).hexdigest() == EXPECTED_SHA256
            and len(data) == EXPECTED_BYTES
            and data.count(b"\n") == EXPECTED_NEWLINES
            and data.endswith(b"\n")
            and not data.startswith(b"\xef\xbb\xbf")
            and b"\r" not in data
        ),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "lines": data.count(b"\n"),
        "expected_sha256": EXPECTED_SHA256,
        "expected_bytes": EXPECTED_BYTES,
        "expected_lines": EXPECTED_NEWLINES,
    }


def verify_input(*, inbox: Path) -> dict:
    path = inbox / "data" / "appts.csv"
    if not path.is_file():
        return {"ok": False, "error": "missing_appts_csv", "wrote": []}
    info = _fingerprint(path)
    info["wrote"] = []
    if not info["ok"]:
        info["error"] = "fingerprint_mismatch"
    return info


def _inventory(rows: list[dict]) -> dict:
    statuses = sorted({row["status"] for row in rows})
    depts = sorted({row["dept"] for row in rows})
    months = sorted({row["visit_date"][:7] for row in rows})
    return {
        "row_count": len(rows),
        "columns": ["appt_id", "patient_id", "dept", "visit_date", "fee_cents", "status"],
        "observed_statuses": statuses,
        "observed_departments": depts,
        "observed_months": months,
    }


def _complaints_from_card(inbox: Path) -> str:
    card = (inbox / "CARD.md").read_text(encoding="utf-8")
    marker = "## 四、客户抱怨原文（唯一线索，无规则编号）"
    if marker not in card:
        raise ValueError("CARD.md is missing the official complaint section")
    rest = card.split(marker, 1)[1]
    next_heading = rest.find("\n## ")
    section = rest if next_heading < 0 else rest[:next_heading]
    text = section.strip()
    if "1）" not in text or "4）" not in text:
        raise ValueError("CARD.md complaint section is incomplete")
    return text


def _extract_interpretations(parsed: dict) -> list[dict]:
    items = parsed.get("interpretations") or parsed.get("items") or parsed.get("interpretation")
    if items is None and all(k in parsed for k in ("complaint", "understood_as", "target_path", "fix")):
        items = [parsed]
    if not isinstance(items, list) or len(items) != 4:
        raise ValueError("model did not return exactly 4 interpretations")
    cleaned = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"interpretation {index} is not an object")
        complaint = item.get("complaint")
        if complaint != index and complaint != str(index):
            if not isinstance(complaint, int):
                complaint = index
        if int(complaint) != index:
            raise ValueError(f"interpretation {index} has complaint={complaint}")
        understood = item.get("understood_as")
        target = item.get("target_path")
        fix = item.get("fix")
        if not isinstance(understood, str) or not understood.strip():
            raise ValueError(f"interpretation {index} is missing understood_as")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"interpretation {index} is missing target_path")
        if not isinstance(fix, str) or not fix.strip():
            raise ValueError(f"interpretation {index} is missing fix")
        cleaned.append(
            {
                "complaint": index,
                "understood_as": understood.strip(),
                "target_path": target.strip(),
                "fix": fix.strip(),
            }
        )
    return cleaned


def interpret_complaint(*, inbox: Path) -> dict:
    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    csv_path = inbox / "data" / "appts.csv"
    info = _fingerprint(csv_path)
    if not info["ok"]:
        return {"ok": False, "error": "fingerprint_mismatch", "wrote": []}

    rows = load_appointments(csv_path)
    candidate_v3 = json.loads((inbox / "candidate_v3.json").read_text(encoding="utf-8"))
    complaints = _complaints_from_card(inbox)
    inventory = _inventory(rows)

    system = (
        "You are interpreting a customer's natural-language complaints about a finance report. "
        "The customer did not give rule numbers. Do not invent official rule IDs such as R1-R4. "
        "Read the complaints, the current candidate report, and the appointment data inventory. "
        "Return a single JSON object with exactly these keys:\n"
        "1) interpretations: an array of 4 objects, in complaint order 1-4, each with "
        "complaint (number), understood_as (string), target_path (string, the report path to fix), "
        "and fix (string).\n"
        "2) recount_plan: an object a deterministic engine will apply to the CSV. Required keys:\n"
        "- include_statuses: array of status strings to include in counts and revenue;\n"
        "- include_departments: array of department codes that must appear in by_dept, "
        "including a department even if its count would be 0;\n"
        "- amount_format: one of two_decimal_string, json_number, leave_as_is;\n"
        "- preserve_paths: array of report paths whose values must not be recomputed from the CSV "
        "(for example [\"by_month\"] only if the customer asked not to change that block).\n"
        "Do not include any other top-level keys. Do not write a finished candidate report. "
        "The recount_plan must come from your reading of the complaints, not from hidden rules."
    )
    user = json.dumps(
        {
            "task_id": "DS-T5-20261112",
            "candidate_v3": candidate_v3,
            "customer_complaints": complaints,
            "data_inventory": inventory,
        },
        ensure_ascii=False,
        indent=2,
    )

    result = chat_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=MODEL,
        timeout=180,
    )
    parsed = result["parsed"]
    interpretations = _extract_interpretations(parsed)
    plan = validate_plan(parsed.get("recount_plan"))

    usage = {
        "step": "interpret_complaint",
        "model": result["model"],
        "requested_model": result["requested_model"],
        "calls": 1,
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "total_tokens": result["total_tokens"],
        "prompt_cache_hit_tokens": result["prompt_cache_hit_tokens"],
        "prompt_cache_miss_tokens": result["prompt_cache_miss_tokens"],
        "estimated_cny": result["estimated_cny"],
        "estimated_cny_exact": result["estimated_cny_exact"],
        "tariff_window": result["tariff_window"],
        "tariff": result["tariff"],
        "pricing_source": result["pricing_source"],
        "thinking_mode": result["thinking_mode"],
        "started_at": result["started_at"],
        "api_id": result["id"],
    }
    exact = float(result["estimated_cny_exact"])
    if exact > CAP_CNY:
        _write_json(out / "model_usage.json", usage)
        return {
            "ok": False,
            "error": "estimated_cny_exceeds_d023_cap",
            "wrote": ["deliverables/model_usage.json"],
            "estimated_cny": result["estimated_cny"],
        }

    _write_json(out / "interpretation.json", interpretations)
    _write_json(out / "recount_plan.json", plan)
    _write_json(out / "model_usage.json", usage)
    return {
        "ok": True,
        "wrote": [
            "deliverables/interpretation.json",
            "deliverables/recount_plan.json",
            "deliverables/model_usage.json",
        ],
        "calls": 1,
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "estimated_cny": result["estimated_cny"],
        "model": result["model"],
    }


def revise(*, inbox: Path, task_id: str) -> dict:
    out = inbox / "deliverables"
    plan_path = out / "recount_plan.json"
    if not plan_path.is_file():
        return {"ok": False, "error": "missing_recount_plan", "wrote": []}
    plan = validate_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    rows = load_appointments(inbox / "data" / "appts.csv")
    candidate_v3 = json.loads((inbox / "candidate_v3.json").read_text(encoding="utf-8"))
    candidate_v4 = apply_recount(rows, plan, candidate_v3)
    _write_json(out / "candidate_v4.json", candidate_v4)
    return {
        "ok": True,
        "wrote": ["deliverables/candidate_v4.json"],
        "error": None,
        "task_id": task_id,
        "preserve_paths": plan["preserve_paths"],
    }
