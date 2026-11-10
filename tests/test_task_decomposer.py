"""Fail-closed tests for goal + schema derivation.

These tests lock three claims:
- two differently structured inputs produce different job-title sets
- the same input produces the same jobs
- the result is not a map from a card id or a fixture name
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.task_decomposer import TaskDecomposer, get_decomposer


HISTORICAL_TITLES = {
    "generate_or_verify_orders_csv",
    "monthly_summary",
    "anomaly_list",
    "evidence_pack_manifest",
}

CASE_A_STATEMENT = (
    "Frozen tabular orders: produce a monthly operating summary, an anomaly list, "
    "and an independently verifiable evidence pack."
)
CASE_B_STATEMENT = (
    "Support tickets: SLA breach list by priority, weekly backlog aging, "
    "and an independently verifiable evidence pack."
)

CASE_A_COLUMNS = [
    {"name": "order_id"},
    {"name": "order_date"},
    {"name": "amount"},
    {"name": "status"},
    {"name": "customer_id"},
    {"name": "channel"},
]
CASE_B_COLUMNS = [
    {"name": "ticket_id"},
    {"name": "opened_at"},
    {"name": "first_response_at"},
    {"name": "resolved_at"},
    {"name": "priority"},
]


def case_a() -> dict:
    return {
        "statement": CASE_A_STATEMENT,
        "schema": {"columns": [dict(column) for column in CASE_A_COLUMNS]},
    }


def case_b() -> dict:
    return {
        "statement": CASE_B_STATEMENT,
        "schema": {"columns": [dict(column) for column in CASE_B_COLUMNS]},
    }


def _titles(jobs: list[dict]) -> list[str]:
    return [job["title"] for job in jobs]


def _kinds(jobs: list[dict]) -> list[str]:
    return [job["kind"] for job in jobs]


def test_case_a_and_case_b_title_sets_differ():
    decomposer = get_decomposer()
    jobs_a = decomposer.decompose(case_a())
    jobs_b = decomposer.decompose(case_b())
    titles_a = _titles(jobs_a)
    titles_b = _titles(jobs_b)

    assert titles_a == [
        "verify_input_schema_keyed_by_order_id",
        "aggregate_amount_by_month_of_order_date",
        "list_anomalies_on_status_amount",
        "assemble_evidence_pack_over_calendar_date_dimension_identifier_measure_status",
    ]
    assert titles_b == [
        "verify_input_schema_keyed_by_ticket_id",
        "list_sla_breaches_by_priority_from_opened_at_to_first_response_at",
        "age_backlog_by_week_of_opened_at_until_resolved_at",
        "assemble_evidence_pack_over_event_time_identifier_priority",
    ]
    assert set(titles_a) != set(titles_b)
    assert set(titles_a).isdisjoint(titles_b)
    assert HISTORICAL_TITLES.isdisjoint(titles_a)
    assert HISTORICAL_TITLES.isdisjoint(titles_b)
    assert _kinds(jobs_a) == [
        "verify_input_schema",
        "temporal_aggregate",
        "anomaly_list",
        "evidence_pack",
    ]
    assert _kinds(jobs_b) == [
        "verify_input_schema",
        "sla_breach_list",
        "backlog_aging",
        "evidence_pack",
    ]
    assert [job["job_id"] for job in jobs_a] == ["J1", "J2", "J3", "J4"]
    assert [job["job_id"] for job in jobs_b] == ["J1", "J2", "J3", "J4"]
    assert all(job["status"] == "PENDING" for job in jobs_a + jobs_b)


def test_same_input_is_deterministic():
    decomposer = TaskDecomposer()
    first = decomposer.decompose(case_a())
    second = decomposer.decompose(case_a())
    assert first == second
    assert decomposer.decompose(case_b()) == get_decomposer().decompose(case_b())


def test_card_id_and_schema_name_do_not_select_jobs():
    decomposer = get_decomposer()
    plain_b = decomposer.decompose(case_b())
    mislabeled = case_b()
    mislabeled["task_id"] = "DS-T1-20261108"
    mislabeled["fixture"] = "DS-T1-20261108"
    mislabeled["fixture_name"] = "orders.csv"
    mislabeled["card_id"] = "case_a"
    mislabeled["schema"]["name"] = "orders.csv"
    assert decomposer.decompose(mislabeled) == plain_b

    plain_a = decomposer.decompose(case_a())
    renamed = case_a()
    renamed["task_id"] = "SUPPORT-TICKETS"
    renamed["fixture_name"] = "tickets.csv"
    renamed["schema"]["name"] = "tickets"
    assert decomposer.decompose(renamed) == plain_a


def test_reworded_statement_with_same_intents_and_schema_matches():
    decomposer = get_decomposer()
    reworded = case_a()
    reworded["statement"] = (
        "Frozen extract. Need a monthly summary, an anomaly list, "
        "and an evidence pack that is independently verifiable."
    )
    assert decomposer.decompose(reworded) == decomposer.decompose(case_a())


def test_unseen_invoice_schema_composes_titles_from_its_columns():
    jobs = get_decomposer().decompose({
        "task_id": "never-seen-fixture",
        "fixture_name": "invoices.csv",
        "statement": (
            "Frozen extract: monthly operating summary, an anomaly list, "
            "and an independently verifiable evidence pack."
        ),
        "schema": {
            "name": "invoices",
            "columns": ["invoice_id", "invoice_date", "revenue", "payment_status"],
        },
    })
    assert _titles(jobs) == [
        "verify_input_schema_keyed_by_invoice_id",
        "aggregate_revenue_by_month_of_invoice_date",
        "list_anomalies_on_payment_status_revenue",
        "assemble_evidence_pack_over_calendar_date_identifier_measure_status",
    ]
    assert HISTORICAL_TITLES.isdisjoint(_titles(jobs))


def test_unseen_ticket_shape_is_not_the_canonical_case_b_titles():
    jobs = get_decomposer().decompose({
        "statement": (
            "SLA breach list by tier, weekly backlog aging, "
            "and an independently verifiable evidence pack."
        ),
        "schema": {"columns": ["created_at", "responded_at", "closed_at", "tier"]},
    })
    assert _titles(jobs) == [
        "verify_input_schema",
        "list_sla_breaches_by_tier_from_created_at_to_responded_at",
        "age_backlog_by_week_of_created_at_until_closed_at",
        "assemble_evidence_pack_over_dimension_event_time",
    ]
    assert set(_titles(jobs)).isdisjoint(_titles(get_decomposer().decompose(case_b())))


def test_declared_numeric_type_promotes_an_unknown_measure_name():
    jobs = get_decomposer().decompose({
        "statement": "monthly summary",
        "schema": {"columns": [
            {"name": "shipped_day"},
            {"name": "weight", "type": "float"},
        ]},
    })
    assert _titles(jobs) == ["aggregate_weight_by_month_of_shipped_day"]
    assert _kinds(jobs) == ["temporal_aggregate"]


def test_goal_words_without_supporting_columns_do_not_emit_that_job():
    decomposer = get_decomposer()
    orders_schema_ticket_goal = {
        "statement": CASE_B_STATEMENT,
        "schema": {"columns": [dict(column) for column in CASE_A_COLUMNS]},
    }
    ticket_schema_orders_goal = {
        "statement": CASE_A_STATEMENT,
        "schema": {"columns": [dict(column) for column in CASE_B_COLUMNS]},
    }
    crossed_orders = decomposer.decompose(orders_schema_ticket_goal)
    crossed_tickets = decomposer.decompose(ticket_schema_orders_goal)

    assert "temporal_aggregate" not in _kinds(crossed_orders)
    assert "anomaly_list" not in _kinds(crossed_orders)
    assert "sla_breach_list" not in _kinds(crossed_orders)
    assert "backlog_aging" not in _kinds(crossed_orders)
    assert _titles(crossed_orders) == [
        "verify_input_schema_keyed_by_order_id",
        "assemble_evidence_pack_over_calendar_date_dimension_identifier_measure_status",
    ]

    assert "temporal_aggregate" not in _kinds(crossed_tickets)
    assert "anomaly_list" not in _kinds(crossed_tickets)
    assert "sla_breach_list" not in _kinds(crossed_tickets)
    assert "backlog_aging" not in _kinds(crossed_tickets)
    assert _titles(crossed_tickets) == [
        "verify_input_schema_keyed_by_ticket_id",
        "assemble_evidence_pack_over_event_time_identifier_priority",
    ]


def test_dropping_anomaly_intent_drops_only_that_job():
    goal = case_a()
    goal["statement"] = (
        "Frozen tabular orders: produce a monthly operating summary "
        "and an independently verifiable evidence pack."
    )
    jobs = get_decomposer().decompose(goal)
    assert _kinds(jobs) == ["verify_input_schema", "temporal_aggregate", "evidence_pack"]
    assert jobs[-1]["inputs"]["covers"] == ["J1", "J2"]


def test_summary_alone_is_not_a_four_job_template():
    jobs = get_decomposer().decompose({
        "statement": "monthly summary",
        "schema": {"columns": ["order_date", "amount"]},
    })
    assert _titles(jobs) == ["aggregate_amount_by_month_of_order_date"]


def test_measure_order_follows_schema_order():
    first = get_decomposer().decompose({
        "statement": "monthly summary",
        "schema": {"columns": ["order_date", "amount", "revenue"]},
    })
    second = get_decomposer().decompose({
        "statement": "monthly summary",
        "schema": {"columns": ["order_date", "revenue", "amount"]},
    })
    assert _titles(first) == ["aggregate_amount_revenue_by_month_of_order_date"]
    assert _titles(second) == ["aggregate_revenue_amount_by_month_of_order_date"]


def test_no_rule_match_returns_empty_list():
    decomposer = get_decomposer()
    assert decomposer.decompose({}) == []
    assert decomposer.decompose({"statement": "hello", "schema": {"columns": ["order_id"]}}) == []
    assert decomposer.decompose({"statement": "monthly summary"}) == []
    assert decomposer.decompose({
        "statement": "你好，只是打个招呼",
        "schema": {"columns": [dict(column) for column in CASE_A_COLUMNS]},
    }) == []


def test_non_dict_goal_fails_closed():
    try:
        get_decomposer().decompose(["monthly summary"])  # type: ignore[arg-type]
        raise AssertionError("expected TypeError")
    except TypeError:
        pass


def test_decomposer_source_has_no_card_lookup():
    source = (ROOT / "control_plane" / "task_decomposer.py").read_text(encoding="utf-8")
    for banned in (
        "DS-T1",
        "DS-T2",
        "generate_or_verify_orders_csv",
        "monthly_summary",
        "evidence_pack_manifest",
        "orders.csv",
    ):
        assert banned not in source


def test_evidence_dump_matches_live_derivation():
    dump_path = ROOT / "docs" / "l2-derivation-evidence.json"
    dump = json.loads(dump_path.read_text(encoding="utf-8"))
    decomposer = get_decomposer()

    assert dump["claim_boundary"] == {
        "l2_granted": False,
        "l2_accepted": False,
        "production_7x24": "NOT ACCEPTED",
        "l2_2_72h_clock": "NOT STARTED",
        "new_frozen_observation_task": False,
        "t1_or_t2_rerun": False,
    }
    assert dump["historical"]["decomposer_before_this_change"] == "returned []"
    assert dump["historical"]["job_titles"] == [
        "generate_or_verify_orders_csv",
        "monthly_summary",
        "anomaly_list",
        "evidence_pack_manifest",
    ]
    assert dump["historical"]["derived_by_decompose"] is False

    for key, builder in (("case_a", case_a), ("case_b", case_b)):
        recorded = dump[key]
        assert recorded["input"]["statement"] == builder()["statement"]
        assert recorded["input"]["schema"]["columns"] == builder()["schema"]["columns"]
        assert recorded["jobs"] == decomposer.decompose(builder())

    cross_orders = {
        "statement": CASE_B_STATEMENT,
        "schema": {"columns": [dict(column) for column in CASE_A_COLUMNS]},
    }
    cross_tickets = {
        "statement": CASE_A_STATEMENT,
        "schema": {"columns": [dict(column) for column in CASE_B_COLUMNS]},
    }
    assert dump["cross_orders_schema_with_case_b_goal"]["jobs"] == decomposer.decompose(cross_orders)
    assert dump["cross_ticket_schema_with_case_a_goal"]["jobs"] == decomposer.decompose(cross_tickets)

    note = (ROOT / "docs" / "l2-derivation-evidence.md").read_text(encoding="utf-8")
    for title in _titles(decomposer.decompose(case_a())) + _titles(decomposer.decompose(case_b())):
        assert title in note
    for phrase in (
        "NOT ACCEPTED",
        "NOT STARTED",
        "not granted",
        "not accepted",
        "returned []",
        "generate_or_verify_orders_csv",
        "monthly_summary",
        "anomaly_list",
        "evidence_pack_manifest",
    ):
        assert phrase in note
    assert "L2 is granted" not in note
    assert "L2 accepted" not in note
    assert "7×24 is accepted" not in note
    assert "72h clock is started" not in note
