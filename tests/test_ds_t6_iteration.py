"""Offline tests for DS-T6 bounded self-iteration. These tests do not call a model API."""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from control_plane.appointment_rules import load_appointments
from control_plane.deepseek_client import format_cny
from control_plane.iteration_loop import decide_stop, format_total_cny, orchestrate
from control_plane.iteration_plan import apply_iteration_plan, validate_iteration_plan
from control_plane.iteration_verifier import score_candidate

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "task_inbox" / "DS-T6-20261114"
CSV = INBOX / "data" / "appts.csv"
V0 = INBOX / "candidate_v0.json"
INPUT_SHA = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"

# Known completed-only values, used only to assert the offline verifier and
# applicator. They are not wired into a model-bypass path.
EXPECTED_TOTAL = "142586.10"
EXPECTED_DEPT = {
    "med": (64, "33498.79"),
    "surg": (49, "28287.69"),
    "ped": (65, "45038.37"),
    "derm": (56, "35761.25"),
}


def _load_v0() -> dict:
    return json.loads(V0.read_text(encoding="utf-8"))


def _rows():
    return load_appointments(CSV)


def _plan(rule: str, reasoning: str, patch: dict) -> dict:
    return {"rule_targeted": rule, "model_reasoning": reasoning, "patch": patch}


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_v0_scores_1_of_5_r3_only():
    score = score_candidate(_load_v0(), _rows(), INPUT_SHA)
    assert score["score"] == "1/5"
    assert score["passing"] == ["R3"]
    assert score["failing"] == ["R1", "R2", "R4", "R5"]
    assert score["checks"]["R3"]["pass"] is True


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_r1_only_stringifies_amounts_and_does_not_fix_other_rules():
    plan = _plan("R1", "先把金额改成两位小数字符串，其它字段先不动。", {"op": "format_amounts", "amount_format": "two_decimal_string"})
    revised = apply_iteration_plan(_load_v0(), _rows(), plan, INPUT_SHA)
    score = score_candidate(revised, _rows(), INPUT_SHA)
    assert score["checks"]["R1"]["pass"] is True
    assert score["checks"]["R2"]["pass"] is False
    assert score["checks"]["R3"]["pass"] is True
    assert score["checks"]["R4"]["pass"] is False
    assert score["checks"]["R5"]["pass"] is False
    assert revised["total_revenue"] == "186035.32"
    assert "derm" not in revised["by_dept"]
    assert "generated_from" not in revised


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_r2_only_adds_missing_department():
    plan = _plan(
        "R2",
        "补上缺失的皮肤科，计数口径先与现有科室保持一致。",
        {"op": "ensure_departments", "departments": ["med", "surg", "ped", "derm"], "include_statuses": ["completed", "cancelled", "no_show"]},
    )
    revised = apply_iteration_plan(_load_v0(), _rows(), plan, INPUT_SHA)
    score = score_candidate(revised, _rows(), INPUT_SHA)
    assert score["checks"]["R2"]["pass"] is True
    assert score["checks"]["R1"]["pass"] is False
    assert score["checks"]["R4"]["pass"] is False
    assert score["checks"]["R5"]["pass"] is False
    assert revised["by_dept"]["derm"]["count"] == 75
    assert revised["by_dept"]["med"]["count"] == 78
    assert revised["total_revenue"] == 186035.32


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_r4_only_recounts_completed_without_adding_derm_or_stringifying():
    plan = _plan("R4", "只按已完成预约重算现有科室和总额。", {"op": "filter_statuses", "include_statuses": ["completed"]})
    revised = apply_iteration_plan(_load_v0(), _rows(), plan, INPUT_SHA)
    score = score_candidate(revised, _rows(), INPUT_SHA)
    assert score["checks"]["R4"]["pass"] is True
    assert score["checks"]["R1"]["pass"] is False
    assert score["checks"]["R2"]["pass"] is False
    assert score["checks"]["R5"]["pass"] is False
    assert "derm" not in revised["by_dept"]
    assert revised["by_dept"]["med"]["count"] == 64
    assert not isinstance(revised["total_revenue"], str)


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_r5_only_sets_generated_from():
    plan = _plan("R5", "补上输入指纹字段。", {"op": "set_generated_from", "value": "input_sha256"})
    revised = apply_iteration_plan(_load_v0(), _rows(), plan, INPUT_SHA)
    score = score_candidate(revised, _rows(), INPUT_SHA)
    assert score["checks"]["R5"]["pass"] is True
    assert score["checks"]["R1"]["pass"] is False
    assert score["checks"]["R2"]["pass"] is False
    assert score["checks"]["R4"]["pass"] is False
    assert revised["generated_from"] == INPUT_SHA
    assert revised["total_revenue"] == 186035.32


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_four_single_rule_steps_reach_known_completed_values():
    rows = _rows()
    candidate = _load_v0()
    plans = [
        _plan("R1", "格式化金额。", {"op": "format_amounts", "amount_format": "two_decimal_string"}),
        _plan("R2", "补科室。", {"op": "ensure_departments", "departments": ["med", "surg", "ped", "derm"], "include_statuses": ["completed"]}),
        _plan("R4", "只计已完成。", {"op": "filter_statuses", "include_statuses": ["completed"]}),
        _plan("R5", "写指纹。", {"op": "set_generated_from", "value": INPUT_SHA}),
    ]
    for plan in plans:
        candidate = apply_iteration_plan(candidate, rows, plan, INPUT_SHA)
    score = score_candidate(candidate, rows, INPUT_SHA)
    assert score["score"] == "5/5"
    assert candidate["total_revenue"] == EXPECTED_TOTAL
    for dept, (count, revenue) in EXPECTED_DEPT.items():
        assert candidate["by_dept"][dept]["count"] == count
        assert candidate["by_dept"][dept]["revenue"] == revenue
    assert candidate["by_month"]["2026-03"] == "14048.10"
    assert candidate["generated_from"] == INPUT_SHA


def test_validate_plan_rejects_mismatched_op():
    with pytest.raises(ValueError):
        validate_iteration_plan(
            _plan("R1", "错配操作。", {"op": "filter_statuses", "include_statuses": ["completed"]})
        )


def test_validate_plan_rejects_second_patch_key():
    plan = _plan("R1", "一次只许一项。", {"op": "format_amounts", "amount_format": "two_decimal_string"})
    plan["recount_plan"] = {"include_statuses": ["completed"]}
    with pytest.raises(ValueError):
        validate_iteration_plan(plan)


def test_decide_stop_prefers_score_5_then_rounds_then_no_improvement():
    assert decide_stop(passed=5, rounds=4, no_improve_streak=0, max_rounds=8, no_improve_limit=2) == "SCORE_5"
    assert decide_stop(passed=5, rounds=8, no_improve_streak=2, max_rounds=8, no_improve_limit=2) == "SCORE_5"
    assert decide_stop(passed=4, rounds=8, no_improve_streak=0, max_rounds=8, no_improve_limit=2) == "ROUNDS_8"
    assert decide_stop(passed=4, rounds=3, no_improve_streak=2, max_rounds=8, no_improve_limit=2) == "NO_IMPROVEMENT"
    assert decide_stop(passed=3, rounds=3, no_improve_streak=1, max_rounds=8, no_improve_limit=2) is None


def _mock_items(*plans: dict, cost: str = "0.000150") -> list[dict]:
    items = []
    for index, plan in enumerate(plans, start=1):
        items.append(
            {
                "parsed": plan,
                "prompt_tokens": 80 + index,
                "completion_tokens": 40 + index,
                "total_tokens": 120 + 2 * index,
                "estimated_cny_exact": cost,
                "estimated_cny": format_cny(Decimal(cost)),
                "id": f"mock-{index}",
            }
        )
    return items



def _isolated_inbox(tmp_path: Path) -> Path:
    dest = tmp_path / "inbox"
    shutil.copytree(
        INBOX,
        dest,
        ignore=shutil.ignore_patterns("deliverables", "__pycache__"),
    )
    (dest / "deliverables").mkdir(parents=True, exist_ok=True)
    return dest

def _write_mock(tmp_path: Path, items: list[dict]) -> Path:
    path = tmp_path / "mock_chat.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_mocked_loop_reaches_5_of_5_in_four_rounds_and_stops(tmp_path, monkeypatch):
    plans = [
        _plan("R1", "先统一金额格式。", {"op": "format_amounts", "amount_format": "two_decimal_string"}),
        _plan("R2", "补上皮肤科。", {"op": "ensure_departments", "departments": ["med", "surg", "ped", "derm"], "include_statuses": ["completed"]}),
        _plan("R4", "只统计已完成预约。", {"op": "filter_statuses", "include_statuses": ["completed"]}),
        _plan("R5", "写入输入指纹。", {"op": "set_generated_from", "value": "input_sha256"}),
        _plan("R3", "不应再调用。", {"op": "ensure_months", "include_statuses": ["completed"]}),
    ]
    mock = _write_mock(tmp_path, _mock_items(*plans, cost="0.000200"))
    monkeypatch.setenv("AISTUDIOOS_CHAT_JSON_MOCK", str(mock))
    inbox = _isolated_inbox(tmp_path)
    result = orchestrate(inbox=inbox, repo_root=ROOT)
    assert result["ok"] is True
    assert result["stop_reason"] == "SCORE_5"
    assert result["rounds"] == 4
    assert result["final_score"] == "5/5"
    assert result["goal_status"] == "ACHIEVED"
    assert result["paid_api_called"] is False
    stop = json.loads((inbox / "deliverables" / "stop_report.json").read_text(encoding="utf-8"))
    assert stop["stop_reason"] == "SCORE_5"
    assert stop["rounds"] == 4
    assert stop["total_tokens"] == (122 + 124 + 126 + 128)
    lines = (inbox / "deliverables" / "iterations.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    targeted = [json.loads(line)["rule_targeted"] for line in lines]
    assert targeted == ["R1", "R2", "R4", "R5"]
    costs = [Decimal(json.loads(line)["cost_cny_exact"]) for line in lines]
    assert sum(costs) == Decimal("0.000800")
    assert stop["total_cost_cny"] == format_total_cny(sum(costs), costs)
    final = json.loads((inbox / "deliverables" / "final_candidate.json").read_text(encoding="utf-8"))
    assert final["total_revenue"] == EXPECTED_TOTAL
    assert final["generated_from"] == INPUT_SHA
    verifier = json.loads((inbox / "deliverables" / "verifier_final.json").read_text(encoding="utf-8"))
    assert verifier["score"] == "5/5"
    assert all(verifier["checks"][rule]["pass"] for rule in ("R1", "R2", "R3", "R4", "R5"))
    # The fifth canned plan must not have been consumed.
    assert int((mock.with_suffix(mock.suffix + ".idx")).read_text()) == 4


@pytest.mark.skipif(not CSV.is_file(), reason="prep csv not on this machine")
def test_mocked_loop_stops_after_two_consecutive_no_improvement(tmp_path, monkeypatch):
    # All-status recount leaves v0's R4 failing, so two such rounds do not improve.
    plans = [
        _plan("R4", "先按全部状态重算，分数不会因此提高。", {"op": "filter_statuses", "include_statuses": ["completed", "cancelled", "no_show"]}),
        _plan("R4", "再次按全部状态重算，仍然没有提高。", {"op": "filter_statuses", "include_statuses": ["completed", "cancelled", "no_show"]}),
        _plan("R1", "不应再调用。", {"op": "format_amounts", "amount_format": "two_decimal_string"}),
    ]
    mock = _write_mock(tmp_path, _mock_items(*plans))
    monkeypatch.setenv("AISTUDIOOS_CHAT_JSON_MOCK", str(mock))
    inbox = _isolated_inbox(tmp_path)
    result = orchestrate(inbox=inbox, repo_root=ROOT)
    assert result["ok"] is True
    assert result["stop_reason"] == "NO_IMPROVEMENT"
    assert result["rounds"] == 2
    assert result["final_score"] == "1/5"
    assert result["goal_status"] == "PARTIAL"
    assert int((mock.with_suffix(mock.suffix + ".idx")).read_text()) == 2


def test_mocked_loop_stops_at_round_cap(tmp_path, monkeypatch):
    plans = [
        _plan("R1", "格式化金额。", {"op": "format_amounts", "amount_format": "two_decimal_string"}),
        _plan("R2", "补科室。", {"op": "ensure_departments", "departments": ["med", "surg", "ped", "derm"], "include_statuses": ["completed"]}),
        _plan("R4", "不应再调用。", {"op": "filter_statuses", "include_statuses": ["completed"]}),
    ]
    mock = _write_mock(tmp_path, _mock_items(*plans))
    monkeypatch.setenv("AISTUDIOOS_CHAT_JSON_MOCK", str(mock))
    inbox = _isolated_inbox(tmp_path)
    result = orchestrate(inbox=inbox, repo_root=ROOT, max_rounds=2)
    assert result["ok"] is True
    assert result["stop_reason"] == "ROUNDS_8"
    assert result["rounds"] == 2
    assert result["final_score"] == "3/5"
    assert result["goal_status"] == "PARTIAL"
    assert int((mock.with_suffix(mock.suffix + ".idx")).read_text()) == 2


def test_format_total_cny_matches_sum_of_round_displays():
    parts = [Decimal("0.0015530"), Decimal("0.0012996"), Decimal("0.0011866"), Decimal("0.0011796")]
    displayed = [Decimal(format_cny(part)) for part in parts]
    total = format_total_cny(sum(parts), parts)
    assert Decimal(total) == sum(displayed)
    assert total != "0.01"
    assert total == "0.00522"
