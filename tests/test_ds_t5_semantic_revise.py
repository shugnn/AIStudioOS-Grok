"""Offline tests for DS-T5 recount application. These tests do not call a model API."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from control_plane.appointment_rules import load_appointments
from control_plane.deepseek_client import estimate_cny, format_cny, tariff_window
from control_plane.recount_plan import apply_recount, months_preserved, validate_plan
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PREP_CSV = ROOT / "task_inbox" / "DS-T5-20261112" / "data" / "appts.csv"
PREP_V3 = ROOT / "task_inbox" / "DS-T5-20261112" / "candidate_v3.json"


def test_validate_plan_rejects_empty_statuses():
    with pytest.raises(ValueError):
        validate_plan({"include_statuses": [], "include_departments": ["med"], "amount_format": "two_decimal_string", "preserve_paths": []})


def test_tariff_window_friday_morning_is_idle():
    moment = datetime(2026, 11, 13, 7, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert tariff_window(moment) == "idle"
    moment_peak = datetime(2026, 11, 13, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert tariff_window(moment_peak) == "peak"


def test_format_cny_keeps_small_nonzero_amounts():
    assert format_cny(Decimal("0")) == "0.00"
    assert format_cny(Decimal("1.234")) == "1.23"
    text = format_cny(Decimal("0.0008"))
    assert text != "0.00"
    assert Decimal(text) == Decimal("0.0008") or Decimal(text) > 0


def test_estimate_cny_idle_flash():
    exact, window, _ = estimate_cny(prompt_tokens=1000, completion_tokens=500, cache_hit_tokens=0, window="idle")
    # 1000 * 1 / 1e6 + 500 * 4 / 1e6 = 0.001 + 0.002 = 0.003
    assert window == "idle"
    assert exact == Decimal("0.003")


@pytest.mark.skipif(not PREP_CSV.is_file(), reason="prep csv not on this machine")
def test_completed_only_plan_preserves_month_values():
    rows = load_appointments(PREP_CSV)
    v3 = json.loads(PREP_V3.read_text(encoding="utf-8"))
    plan = {
        "include_statuses": ["completed"],
        "include_departments": ["med", "surg", "ped", "derm"],
        "amount_format": "two_decimal_string",
        "preserve_paths": ["by_month"],
    }
    v4 = apply_recount(rows, plan, v3)
    assert months_preserved(v3, v4)
    assert v4["by_dept"]["derm"]["count"] == 56
    assert v4["total_revenue"] == "142586.10"
    assert v4["by_month"]["2026-03"] == "14048.10"
