"""Worker for DS-T6-20261114. Invoked only as a step of scripts/worker_run_task.py.

Each propose_fix step must call a model (or a test mock when
AISTUDIOOS_CHAT_JSON_MOCK is set). The Worker does not score R1-R5 and does
not write verifier_final.json.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from control_plane.appointment_rules import load_appointments
from control_plane.deepseek_client import chat_json, format_cny
from control_plane.iteration_plan import apply_iteration_plan, validate_iteration_plan

EXPECTED_SHA256 = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"
EXPECTED_BYTES = 12350
EXPECTED_NEWLINES = 301
CAP_CNY = 5.00
MODEL = "deepseek-flash"
SHANGHAI = ZoneInfo("Asia/Shanghai")
TASK_ID = "DS-T6-20261114"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return {
        "ok": (
            digest == EXPECTED_SHA256
            and len(data) == EXPECTED_BYTES
            and data.count(b"\n") == EXPECTED_NEWLINES
            and data.endswith(b"\n")
            and not data.startswith(b"\xef\xbb\xbf")
            and b"\r" not in data
        ),
        "sha256": digest,
        "bytes": len(data),
        "lines": data.count(b"\n"),
        "expected_sha256": EXPECTED_SHA256,
        "expected_bytes": EXPECTED_BYTES,
        "expected_lines": EXPECTED_NEWLINES,
    }


def _inventory(rows: list[dict]) -> dict:
    return {
        "row_count": len(rows),
        "columns": ["appt_id", "patient_id", "dept", "visit_date", "fee_cents", "status"],
        "observed_statuses": sorted({row["status"] for row in rows}),
        "observed_departments": sorted({row["dept"] for row in rows}),
        "observed_months": sorted({row["visit_date"][:7] for row in rows}),
        "input_sha256": EXPECTED_SHA256,
    }


def prepare_input(*, inbox: Path) -> dict:
    src = inbox / "candidate_v0.json"
    if not src.is_file():
        return {"ok": False, "error": "missing_candidate_v0", "wrote": []}
    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    candidate = json.loads(src.read_text(encoding="utf-8"))
    _write_json(out / "current_candidate.json", candidate)
    return {"ok": True, "wrote": ["deliverables/current_candidate.json"]}


def verify_input(*, inbox: Path) -> dict:
    path = inbox / "data" / "appts.csv"
    if not path.is_file():
        return {"ok": False, "error": "missing_appts_csv", "wrote": []}
    info = _fingerprint(path)
    info["wrote"] = []
    if not info["ok"]:
        info["error"] = "fingerprint_mismatch"
    return info


def _next_round(out: Path) -> int:
    marker = out / "current_round.json"
    current = 0
    if marker.is_file():
        current = int(json.loads(marker.read_text(encoding="utf-8")).get("round") or 0)
    return current + 1


def _mock_chat_json(path: Path, *, messages: list[dict], model: str = MODEL, timeout: int = 180) -> dict:
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise RuntimeError("mock chat file must be a JSON list")
    idx_path = path.with_suffix(path.suffix + ".idx")
    index = int(idx_path.read_text(encoding="utf-8")) if idx_path.is_file() else 0
    if index >= len(items):
        raise RuntimeError("mock model responses exhausted")
    item = items[index]
    if not isinstance(item, dict) or "parsed" not in item:
        raise RuntimeError("mock model item must contain parsed")
    idx_path.write_text(str(index + 1), encoding="utf-8")
    prompt_tokens = int(item.get("prompt_tokens") or 100)
    completion_tokens = int(item.get("completion_tokens") or 50)
    started = datetime.now(SHANGHAI)
    return {
        "parsed": item["parsed"],
        "model": item.get("model") or f"{model}-mock",
        "requested_model": model,
        "thinking_mode": "disabled",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(item.get("total_tokens") or (prompt_tokens + completion_tokens)),
        "prompt_cache_hit_tokens": int(item.get("prompt_cache_hit_tokens") or 0),
        "prompt_cache_miss_tokens": int(item.get("prompt_cache_miss_tokens") or prompt_tokens),
        "estimated_cny_exact": str(item.get("estimated_cny_exact") or "0.000150"),
        "estimated_cny": item.get("estimated_cny") or format_cny(__import__("decimal").Decimal(str(item.get("estimated_cny_exact") or "0.000150"))),
        "tariff_window": item.get("tariff_window") or "idle",
        "tariff": item.get("tariff") or {},
        "started_at": started.isoformat(timespec="seconds"),
        "pricing_source": "mock",
        "id": item.get("id") or f"mock-{index + 1}",
    }


def _call_model(*, messages: list[dict]) -> dict:
    mock = os.environ.get("AISTUDIOOS_CHAT_JSON_MOCK", "").strip()
    if mock:
        return _mock_chat_json(Path(mock), messages=messages, model=MODEL)
    return chat_json(messages=messages, model=MODEL, timeout=180)


def _extract_plan(parsed: dict) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError("model JSON was not an object")
    if "rule_targeted" in parsed and "patch" in parsed:
        return validate_iteration_plan(parsed)
    # Tolerate a slightly nested response, but not a second patch.
    for key in ("plan", "iteration_plan"):
        nested = parsed.get(key)
        if isinstance(nested, dict) and "rule_targeted" in nested:
            return validate_iteration_plan(nested)
    raise ValueError("model did not return a single-rule iteration plan")


def propose_fix(*, inbox: Path, task_id: str = TASK_ID) -> dict:
    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    csv_path = inbox / "data" / "appts.csv"
    info = _fingerprint(csv_path)
    if not info["ok"]:
        return {"ok": False, "error": "fingerprint_mismatch", "wrote": []}
    candidate_path = out / "current_candidate.json"
    score_path = out / "current_score.json"
    if not candidate_path.is_file() or not score_path.is_file():
        return {"ok": False, "error": "missing_current_state", "wrote": []}
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    score = json.loads(score_path.read_text(encoding="utf-8"))
    if score.get("passed", 0) >= 5:
        return {"ok": False, "error": "already_score_5_refusing_to_iterate", "wrote": []}
    rows = load_appointments(csv_path)
    inventory = _inventory(rows)
    failing = score.get("failing") or []
    checks = {
        rule: {"pass": body.get("pass"), "reason": body.get("reason")}
        for rule, body in (score.get("checks") or {}).items()
    }
    system = (
        "You revise a finance report by iterating one scoring rule per round. "
        "Read the current candidate, the current score, and the failing items. "
        "Pick exactly one currently failing rule and return a single JSON object "
        "with keys rule_targeted, model_reasoning, and patch. "
        "model_reasoning must be Chinese and at most 120 characters. "
        "Allowed patches, and only these:\n"
        'R1 {"op":"format_amounts","amount_format":"two_decimal_string"} '
        "converts existing amounts to two-decimal strings.\n"
        'R2 {"op":"ensure_departments","departments":["med","surg","ped","derm"],'
        '"include_statuses":["..."]} adds only missing departments, counting rows '
        "whose status is in include_statuses.\n"
        'R3 {"op":"ensure_months","include_statuses":["..."]} sorts month keys and '
        "adds any month that appears in the data but is missing from by_month.\n"
        'R4 {"op":"filter_statuses","include_statuses":["..."]} recounts '
        "total_revenue, existing by_dept counts/revenues, and existing by_month "
        "values using only the listed statuses. It must not add departments.\n"
        'R5 {"op":"set_generated_from","value":"input_sha256"} or the literal input SHA256 '
        "sets the top-level generated_from field.\n"
        "Do not target a rule that already passed. Do not emit a finished candidate. "
        "Do not include a second patch or a recount_plan that fixes multiple rules."
    )
    user = json.dumps(
        {
            "task_id": TASK_ID,
            "current_score": score.get("score"),
            "failing": failing,
            "checks": checks,
            "current_candidate": candidate,
            "data_inventory": inventory,
            "scoring_rules": {
                "R1": "all amounts are two-decimal strings",
                "R2": "by_dept contains the four departments med/surg/ped/derm",
                "R3": "by_month keys are ascending and cover all months in the data",
                "R4": "only status=completed counts toward count, revenue, and total_revenue",
                "R5": "top-level generated_from equals the input SHA256",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    result = _call_model(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    plan = _extract_plan(result["parsed"])
    if plan["rule_targeted"] not in failing:
        return {
            "ok": False,
            "error": "model_targeted_non_failing_rule",
            "rule_targeted": plan["rule_targeted"],
            "failing": failing,
            "wrote": [],
        }
    round_no = _next_round(out)
    round_dir = out / "rounds" / f"{round_no:02d}"
    usage = {
        "step": "propose_fix",
        "round": round_no,
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
        "mocked": bool(os.environ.get("AISTUDIOOS_CHAT_JSON_MOCK", "").strip()),
    }
    exact = float(result["estimated_cny_exact"])
    _write_json(round_dir / "plan.json", plan)
    _write_json(round_dir / "model_usage.json", usage)
    _write_json(out / "pending_round.json", {"round": round_no})
    wrote = [
        f"deliverables/rounds/{round_no:02d}/plan.json",
        f"deliverables/rounds/{round_no:02d}/model_usage.json",
        "deliverables/pending_round.json",
    ]
    if exact > CAP_CNY:
        return {
            "ok": False,
            "error": "estimated_cny_exceeds_d023_cap",
            "wrote": wrote,
            "estimated_cny": result["estimated_cny"],
        }
    return {
        "ok": True,
        "wrote": wrote,
        "rule_targeted": plan["rule_targeted"],
        "calls": 1,
        "prompt_tokens": result["prompt_tokens"],
        "completion_tokens": result["completion_tokens"],
        "total_tokens": result["total_tokens"],
        "estimated_cny": result["estimated_cny"],
        "estimated_cny_exact": result["estimated_cny_exact"],
        "model": result["model"],
        "task_id": task_id,
    }


def apply_fix(*, inbox: Path, task_id: str = TASK_ID) -> dict:
    out = inbox / "deliverables"
    pending_path = out / "pending_round.json"
    if not pending_path.is_file():
        return {"ok": False, "error": "missing_pending_round", "wrote": []}
    round_no = int(json.loads(pending_path.read_text(encoding="utf-8"))["round"])
    plan_path = out / "rounds" / f"{round_no:02d}" / "plan.json"
    candidate_path = out / "current_candidate.json"
    csv_path = inbox / "data" / "appts.csv"
    if not plan_path.is_file() or not candidate_path.is_file():
        return {"ok": False, "error": "missing_plan_or_candidate", "wrote": []}
    info = _fingerprint(csv_path)
    if not info["ok"]:
        return {"ok": False, "error": "fingerprint_mismatch", "wrote": []}
    plan = validate_iteration_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    rows = load_appointments(csv_path)
    revised = apply_iteration_plan(candidate, rows, plan, info["sha256"])
    _write_json(out / "rounds" / f"{round_no:02d}" / "candidate.json", revised)
    _write_json(out / "current_candidate.json", revised)
    _write_json(out / "current_round.json", {"round": round_no})
    pending_path.unlink()
    return {
        "ok": True,
        "wrote": [
            f"deliverables/rounds/{round_no:02d}/candidate.json",
            "deliverables/current_candidate.json",
            "deliverables/current_round.json",
        ],
        "rule_targeted": plan["rule_targeted"],
        "task_id": task_id,
    }
