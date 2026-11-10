"""Derive a job list, execute it, and write deliverables.

These tests lock four claims:
- the product path calls decompose() and does not need a pre-written dispatch
- a hand-authored worker_jobs.py is not imported, even if it is present
- execution follows kind + structured inputs, including when the title is a
  historical orders title
- checksums in the evidence pack are the hashes of the files just written

The support-ticket fixture is a local demo. It is not an observation card.
T1 and T2 are not rerun. L2 stays CONDITIONAL.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.derived_worker import execute_jobs, run_card, run_goal
from control_plane.task_decomposer import get_decomposer
from scripts.worker_run_task import main as worker_main


FIXTURE = ROOT / "fixtures" / "local_support_tickets_demo"
T1 = ROOT / "task_inbox" / "DS-T1-20261108"
HISTORICAL_TITLES = {
    "generate_or_verify_orders_csv",
    "monthly_summary",
    "anomaly_list",
    "evidence_pack_manifest",
}
ORDERS_COLUMNS = ["order_id", "order_date", "amount", "status", "customer_id", "channel"]
CLAIM = {
    "l2_granted": False,
    "l2_accepted": False,
    "l2_status": "CONDITIONAL",
    "production_7x24": "NOT ACCEPTED",
    "l2_2_72h_clock": "NOT STARTED",
    "observation_card": False,
    "t3_run": False,
    "t1_or_t2_rerun": False,
}
MONTH_BUCKETS = {
    ("2026-01", "high"): (Decimal("25.00"), 2, 0),
    ("2026-01", "low"): (Decimal("25.50"), 3, 1),
    ("2026-01", "medium"): (Decimal("12.00"), 1, 0),
    ("2026-02", "high"): (Decimal("-3.00"), 1, 0),
    ("2026-02", "low"): (Decimal("1000.00"), 1, 0),
    ("2026-02", "medium"): (Decimal("8.25"), 1, 0),
}
WEEK_BUCKETS = {
    ("2026-W02", "high"): (Decimal("10.00"), 1, 0),
    ("2026-W02", "low"): (Decimal("20.50"), 2, 1),
    ("2026-W03", "high"): (Decimal("15.00"), 1, 0),
    ("2026-W03", "low"): (Decimal("5.00"), 1, 0),
    ("2026-W04", "medium"): (Decimal("12.00"), 1, 0),
    ("2026-W06", "high"): (Decimal("-3.00"), 1, 0),
    ("2026-W06", "medium"): (Decimal("8.25"), 1, 0),
    ("2026-W07", "low"): (Decimal("1000.00"), 1, 0),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _goal() -> dict:
    return _load(FIXTURE / "goal.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    if not root.exists():
        return hashes
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hashes[str(path.relative_to(root))] = _sha(path)
    return hashes


def _copy_fixture(dest: Path) -> Path:
    card = dest / "card"
    shutil.copytree(FIXTURE, card)
    return card


def _rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _parse_ts(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _independent_buckets(csv_path: Path, grain: str) -> tuple[int, dict]:
    buckets: dict[tuple[str, str], dict] = {}
    skipped = 0
    for row in _rows(csv_path):
        raw = row["opened_at"].strip()
        if not raw:
            skipped += 1
            continue
        stamp = _parse_ts(raw)
        if grain == "month":
            period = f"{stamp.year:04d}-{stamp.month:02d}"
        else:
            iso = stamp.isocalendar()
            period = f"{iso.year}-W{iso.week:02d}"
        slot = buckets.setdefault(
            (period, row["priority"]),
            {"rows": 0, "sum": Decimal("0"), "unparsed": 0},
        )
        slot["rows"] += 1
        try:
            slot["sum"] += Decimal(row["labor_amount"].strip())
        except InvalidOperation:
            slot["unparsed"] += 1
    return skipped, buckets


def _payload_buckets(payload: dict) -> dict:
    found = {}
    for bucket in payload["buckets"]:
        found[(bucket["period"], bucket["group"])] = (
            Decimal(bucket["sums"]["labor_amount"]),
            bucket["rows"],
            bucket["unparsed"]["labor_amount"],
        )
    return found


def test_fixture_is_a_local_demo_and_not_an_observation_card():
    assert FIXTURE.parent.name == "fixtures"
    assert "task_inbox" not in FIXTURE.parts
    assert not FIXTURE.name.startswith("DS-")
    assert not (FIXTURE / "dispatch.json").exists()
    assert not (FIXTURE / "worker_jobs.py").exists()
    assert not (FIXTURE / "deliverables").exists()
    goal = _goal()
    assert goal["observation_card"] is False
    assert goal["label"] == "local_demo_not_an_observation_card"
    names = [column["name"] for column in goal["schema"]["columns"]]
    assert names != ORDERS_COLUMNS
    assert "order_id" not in names
    assert "orders" not in goal["statement"].lower()
    readme = (FIXTURE / "README.md").read_text(encoding="utf-8")
    assert "not an observation" in readme.lower()
    inbox = ROOT / "task_inbox"
    inbox_dirs = sorted(path.name for path in inbox.iterdir() if path.is_dir())
    assert "DS-T1-20261108" in inbox_dirs
    assert FIXTURE.name not in inbox_dirs
    assert not (ROOT / "task_inbox" / "DS-T2-20261110").exists()


def test_fixture_derives_ticket_jobs_not_historical_titles():
    jobs = get_decomposer().decompose(_goal())
    titles = [job["title"] for job in jobs]
    kinds = [job["kind"] for job in jobs]
    assert kinds == [
        "verify_input_schema",
        "temporal_aggregate",
        "temporal_aggregate",
        "anomaly_list",
        "sla_breach_list",
        "backlog_aging",
        "evidence_pack",
    ]
    assert HISTORICAL_TITLES.isdisjoint(titles)
    assert jobs[1]["inputs"]["grain"] == "month"
    assert jobs[2]["inputs"]["grain"] == "week"
    assert jobs[1]["inputs"]["measures"] == ["labor_amount"]
    assert jobs[4]["inputs"]["start"] == "opened_at"
    assert jobs[4]["inputs"]["end"] == "first_response_at"
    assert jobs[5]["inputs"]["open"] == "opened_at"
    assert jobs[5]["inputs"]["close"] == "resolved_at"
    planted = _goal()
    planted["task_id"] = "DS-T1-20261108"
    planted["fixture_name"] = "orders.csv"
    planted["schema"]["name"] = "orders.csv"
    assert get_decomposer().decompose(planted) == jobs


def test_run_writes_dispatch_as_output_without_preauthored_files(tmp_path):
    card = _copy_fixture(tmp_path)
    card.rename(tmp_path / "renamed-demo")
    card = tmp_path / "renamed-demo"
    out = tmp_path / "out"
    result = run_card(card, out)
    assert result["ok"] is True
    assert result["error"] is None
    assert result["used_preauthored_dispatch"] is False
    assert result["used_worker_jobs_py"] is False
    assert result["claim_boundary"] == CLAIM
    assert result["network"] is False
    assert result["paid"] is False

    dispatch = _load(out / "derived_dispatch.json")
    live = get_decomposer().decompose(_load(card / "goal.json"))
    assert dispatch["produced_by"] == "control_plane.task_decomposer.TaskDecomposer.decompose"
    assert dispatch["written_after_derivation"] is True
    assert dispatch["read_as_job_source"] is False
    assert dispatch["used_worker_jobs_py"] is False
    assert dispatch["claim_boundary"] == CLAIM
    assert dispatch["ok"] is True
    assert dispatch["ignored_keys"] == ["label", "observation_card"]
    assert [job["title"] for job in dispatch["jobs"]] == [job["title"] for job in live]
    for executed, derived in zip(dispatch["jobs"], live):
        assert executed["job_id"] == derived["job_id"]
        assert executed["kind"] == derived["kind"]
        assert executed["inputs"] == derived["inputs"]
        assert executed["reason"] == derived["reason"]
        assert executed["status"] == "DONE"
        assert executed["error"] is None
        payload = _load(out / executed["output"])
        assert payload["kind"] == derived["kind"]
        assert payload["job_id"] == derived["job_id"]
    assert HISTORICAL_TITLES.isdisjoint(job["title"] for job in dispatch["jobs"])
    assert not (card / "dispatch.json").exists()
    assert not (card / "worker_jobs.py").exists()
    assert not (card / "derived_dispatch.json").exists()

    worklog = _load(out / "worklog.json")
    assert worklog["path"] == "derive_then_execute"
    assert worklog["used_preauthored_dispatch"] is False
    assert worklog["used_worker_jobs_py"] is False
    assert worklog["claim_boundary"] == CLAIM
    step_names = [step["step"] for step in worklog["steps"]]
    assert step_names[0] == "decompose"
    assert step_names[-1] == "write_derived_dispatch"
    assert "execute" in step_names
    assert step_names.index("decompose") < step_names.index("execute")
    assert step_names.index("execute") < step_names.index("write_derived_dispatch")


def test_two_runs_match_except_the_worklog_clock(tmp_path):
    card = _copy_fixture(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert run_card(card, first)["ok"] is True
    assert run_card(card, second)["ok"] is True
    first_files = sorted(path.name for path in first.iterdir())
    second_files = sorted(path.name for path in second.iterdir())
    assert first_files == second_files
    for name in first_files:
        if name == "worklog.json":
            continue
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_poisoned_dispatch_and_worker_jobs_are_not_used(tmp_path):
    card = _copy_fixture(tmp_path)
    (card / "dispatch.json").write_text(json.dumps({
        "jobs": [
            {"job_id": "J1", "title": "generate_or_verify_orders_csv", "status": "PENDING"},
            {"job_id": "J2", "title": "monthly_summary", "status": "PENDING"},
            {"job_id": "J3", "title": "anomaly_list", "status": "PENDING"},
            {"job_id": "J4", "title": "evidence_pack_manifest", "status": "PENDING"},
        ]
    }), encoding="utf-8")
    (card / "worker_jobs.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('decoy_ran.txt').write_text('ran', encoding='utf-8')\n"
        "raise SystemExit('decoy imported')\n",
        encoding="utf-8",
    )
    goal = _load(card / "goal.json")
    goal["task_id"] = "DS-T3-NOT-A-CARD"
    goal["fixture_name"] = "orders.csv"
    (card / "goal.json").write_text(json.dumps(goal), encoding="utf-8")
    out = tmp_path / "out"
    (out).mkdir()
    (out / "derived_dispatch.json").write_text("{", encoding="utf-8")

    before_inbox = [path.name for path in (ROOT / "task_inbox").iterdir()]
    result = run_card(card, out)
    assert result["ok"] is True
    assert not (card / "decoy_ran.txt").exists()
    assert not (out / "decoy_ran.txt").exists()
    dispatch = _load(out / "derived_dispatch.json")
    live = get_decomposer().decompose(goal)
    assert [job["title"] for job in dispatch["jobs"]] == [job["title"] for job in live]
    assert HISTORICAL_TITLES.isdisjoint(job["title"] for job in dispatch["jobs"])
    assert "task_id" in dispatch["ignored_keys"]
    assert "fixture_name" in dispatch["ignored_keys"]
    assert [path.name for path in (ROOT / "task_inbox").iterdir()] == before_inbox


def test_month_and_week_sums_match_hand_checks_and_an_independent_pass(tmp_path):
    card = _copy_fixture(tmp_path)
    out = tmp_path / "out"
    assert run_card(card, out)["ok"] is True
    csv_path = card / "data" / "tickets.csv"
    dispatch = _load(out / "derived_dispatch.json")
    by_grain = {
        job["inputs"]["grain"]: _load(out / job["output"])
        for job in dispatch["jobs"]
        if job["kind"] == "temporal_aggregate"
    }
    assert set(by_grain) == {"month", "week"}
    assert by_grain["month"]["time_column"] == "opened_at"
    assert by_grain["month"]["measures"] == ["labor_amount"]
    assert by_grain["month"]["group_by"] == "priority"
    assert by_grain["month"]["skipped_rows"] == 1
    assert by_grain["week"]["skipped_rows"] == 1
    assert _payload_buckets(by_grain["month"]) == MONTH_BUCKETS
    assert _payload_buckets(by_grain["week"]) == WEEK_BUCKETS

    for grain, expected in (("month", MONTH_BUCKETS), ("week", WEEK_BUCKETS)):
        skipped, buckets = _independent_buckets(csv_path, grain)
        assert skipped == 1
        condensed = {
            key: (slot["sum"], slot["rows"], slot["unparsed"])
            for key, slot in buckets.items()
        }
        assert condensed == expected


def test_anomalies_follow_the_median_rule_and_the_planted_rows(tmp_path):
    card = _copy_fixture(tmp_path)
    out = tmp_path / "out"
    assert run_card(card, out)["ok"] is True
    payload = _load(out / "J4_anomaly_list.json")
    values = []
    for row in _rows(card / "data" / "tickets.csv"):
        try:
            values.append(Decimal(row["labor_amount"].strip()))
        except InvalidOperation:
            continue
    assert len(values) >= 4
    mid = statistics.median(values)
    mad = statistics.median([abs(value - mid) for value in values])
    threshold = mid + (Decimal(3) * mad)
    expected_outliers = {value for value in values if value > threshold}
    assert expected_outliers == {Decimal("1000.00")}
    assert Decimal(payload["column_stats"]["labor_amount"]["threshold"]) == threshold
    flagged = {
        (item["key"], item["column"], item["type"])
        for item in payload["anomalies"]
    }
    assert flagged == {
        ("T-06", "labor_amount", "negative"),
        ("T-06", "status", "missing"),
        ("T-07", "labor_amount", "high_outlier"),
        ("T-09", "labor_amount", "non_numeric"),
    }
    assert payload["column_stats"]["labor_amount"]["high_outlier_applied"] is True
    assert payload["column_stats"]["status"]["numeric"] is False
    assert all(item["key"] != "T-01" for item in payload["anomalies"])


def test_sla_list_has_no_duration_threshold(tmp_path):
    card = _copy_fixture(tmp_path)
    out = tmp_path / "out"
    assert run_card(card, out)["ok"] is True
    payload = _load(out / "J5_sla_breach_list.json")
    assert payload["threshold"] is None
    assert payload["start"] == "opened_at"
    assert payload["end"] == "first_response_at"
    assert payload["group_by"] == "priority"
    found = {(item["key"], item["type"]) for item in payload["breaches"]}
    assert found == {
        ("T-03", "missing_end"),
        ("T-04", "end_before_start"),
        ("T-10", "missing_or_bad_start"),
    }
    assert payload["by_group"] == {"high": 2, "low": 1, "medium": 0}

    independent = set()
    for row in _rows(card / "data" / "tickets.csv"):
        start = row["opened_at"].strip()
        end = row["first_response_at"].strip()
        start_ts = _parse_ts(start) if start else None
        if not start or start_ts is None:
            independent.add((row["ticket_id"], "missing_or_bad_start"))
        elif not end:
            independent.add((row["ticket_id"], "missing_end"))
        else:
            end_ts = _parse_ts(end)
            if end_ts is None:
                independent.add((row["ticket_id"], "bad_end"))
            elif end_ts < start_ts:
                independent.add((row["ticket_id"], "end_before_start"))
    assert independent == found


def test_backlog_ages_against_the_latest_data_timestamp(tmp_path):
    card = _copy_fixture(tmp_path)
    out = tmp_path / "out"
    assert run_card(card, out)["ok"] is True
    payload = _load(out / "J6_backlog_aging.json")
    as_of = datetime(2026, 2, 10, 9, 0, 0)
    t03_age = int((as_of - datetime(2026, 1, 12, 8, 0, 0)).total_seconds())
    t05_age = int((as_of - datetime(2026, 2, 2, 9, 0, 0)).total_seconds())
    assert t03_age == 2509200
    assert t05_age == 691200
    assert payload["as_of"] == "2026-02-10T09:00:00Z"
    assert payload["as_of_rule"] == "max parsed timestamp among the open and close columns"
    assert payload["skipped_open"] == 1
    assert payload["inconsistent"] == []
    by_key = {item["key"]: item for item in payload["backlog"]}
    assert set(by_key) == {"T-03", "T-05"}
    assert by_key["T-03"]["age_seconds"] == t03_age
    assert by_key["T-03"]["period"] == "2026-W03"
    assert by_key["T-05"]["age_seconds"] == t05_age
    assert by_key["T-05"]["period"] == "2026-W06"
    buckets = {bucket["period"]: bucket for bucket in payload["buckets"]}
    assert buckets["2026-W02"]["closed_age_seconds_sum"] == 352800
    assert buckets["2026-W02"]["opened"] == 3
    assert buckets["2026-W03"]["still_open"] == 1
    assert buckets["2026-W03"]["open_age_seconds_sum"] == t03_age
    assert payload["as_of"] != _load(out / "worklog.json")["started_utc"]


def test_evidence_pack_hashes_are_recomputed_from_the_files(tmp_path):
    card = _copy_fixture(tmp_path)
    out = tmp_path / "out"
    assert run_card(card, out)["ok"] is True
    pack = _load(out / "J7_evidence_pack.json")
    dispatch = _load(out / "derived_dispatch.json")
    csv_path = card / "data" / "tickets.csv"
    assert pack["input"]["sha256"] == _sha(csv_path)
    assert pack["input"]["bytes"] == csv_path.stat().st_size
    assert pack["covers"] == ["J1", "J2", "J3", "J4", "J5", "J6"]
    assert "derived_dispatch.json" not in pack["outputs"]
    assert "worklog.json" not in pack["outputs"]
    assert pack["excludes"] == ["derived_dispatch.json", "worklog.json", "J7_evidence_pack.json"]
    assert pack["claim_boundary"] == CLAIM
    for name, meta in pack["outputs"].items():
        path = out / name
        assert meta["sha256"] == _sha(path)
        assert meta["bytes"] == path.stat().st_size
    evidence_meta = dispatch["evidence_pack"]
    assert evidence_meta["name"] == "J7_evidence_pack.json"
    assert evidence_meta["sha256"] == _sha(out / "J7_evidence_pack.json")
    assert evidence_meta["bytes"] == (out / "J7_evidence_pack.json").stat().st_size
    assert dispatch["input"]["sha256"] == _sha(csv_path)


def test_schema_mismatch_records_the_derived_list_and_skips_later_jobs(tmp_path):
    card = _copy_fixture(tmp_path)
    csv_path = card / "data" / "tickets.csv"
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    lines[0] = "id,opened_at,first_response_at,resolved_at,priority,status,labor_amount"
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    result = run_card(card, out)
    assert result["ok"] is False
    assert result["error"] == "job_failed"
    dispatch = _load(out / "derived_dispatch.json")
    live = get_decomposer().decompose(_load(card / "goal.json"))
    assert [job["title"] for job in dispatch["jobs"]] == [job["title"] for job in live]
    statuses = {job["job_id"]: job["status"] for job in dispatch["jobs"]}
    assert statuses["J1"] == "FAILED"
    assert statuses["J2"] == "SKIPPED"
    assert statuses["J6"] == "SKIPPED"
    assert statuses["J7"] == "DONE"
    verify = _load(out / "J1_verify_input_schema.json")
    assert verify["problems"] == ["header_mismatch"]
    assert not (out / "J2_temporal_aggregate.json").exists()
    assert not (out / "J5_sla_breach_list.json").exists()
    assert HISTORICAL_TITLES.isdisjoint(job["title"] for job in dispatch["jobs"])


def test_duplicate_and_blank_keys_fail_verification(tmp_path):
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text(
        "ticket_id,opened_at\n"
        "A,2026-01-01T00:00:00Z\n"
        "A,2026-01-02T00:00:00Z\n",
        encoding="utf-8",
    )
    blank = tmp_path / "blank.csv"
    blank.write_text(
        "ticket_id,opened_at\n"
        ",2026-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    goal = {
        "statement": "Frozen table: an independently verifiable evidence pack.",
        "schema": {"columns": ["ticket_id", "opened_at"]},
    }
    duplicate_out = tmp_path / "duplicate-out"
    blank_out = tmp_path / "blank-out"
    duplicate_result = run_goal(goal, duplicate, duplicate_out)
    blank_result = run_goal(goal, blank, blank_out)
    assert duplicate_result["ok"] is False
    assert blank_result["ok"] is False
    assert _load(duplicate_out / "J1_verify_input_schema.json")["duplicate_keys"] == ["A"]
    assert _load(blank_out / "J1_verify_input_schema.json")["blank_keys"] == 1
    for out in (duplicate_out, blank_out):
        titles = [job["title"] for job in _load(out / "derived_dispatch.json")["jobs"]]
        assert titles
        assert HISTORICAL_TITLES.isdisjoint(titles)
        assert "temporal_aggregate" not in [job["kind"] for job in _load(out / "derived_dispatch.json")["jobs"]]


def test_executor_follows_structured_inputs_when_titles_are_historical(tmp_path):
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(
        "invoice_id,invoice_date,revenue,payment_status,opened_at,closed_at\n"
        "I-1,2026-03-02,10.00,paid,2026-03-02T09:00:00Z,\n"
        "I-2,2026-03-09,4.00,paid,2026-03-09T09:00:00Z,2026-03-09T08:00:00Z\n",
        encoding="utf-8",
    )
    jobs = [
        {
            "job_id": "J1",
            "title": "generate_or_verify_orders_csv",
            "kind": "verify_input_schema",
            "status": "PENDING",
            "inputs": {
                "key": "invoice_id",
                "columns": [
                    "invoice_id", "invoice_date", "revenue",
                    "payment_status", "opened_at", "closed_at",
                ],
            },
        },
        {
            "job_id": "J2",
            "title": "monthly_summary",
            "kind": "temporal_aggregate",
            "status": "PENDING",
            "inputs": {
                "grain": "week",
                "measures": ["revenue"],
                "time_column": "invoice_date",
                "group_by": None,
            },
        },
        {
            "job_id": "J3",
            "title": "anomaly_list",
            "kind": "sla_breach_list",
            "status": "PENDING",
            "inputs": {
                "group_by": "payment_status",
                "start": "opened_at",
                "end": "closed_at",
            },
        },
        {
            "job_id": "J4",
            "title": "evidence_pack_manifest",
            "kind": "evidence_pack",
            "status": "PENDING",
            "inputs": {
                "roles": ["identifier", "measure"],
                "covers": ["J1", "J2", "J3"],
            },
        },
    ]
    out = tmp_path / "out"
    result = execute_jobs(jobs, csv_path, out)
    assert result["ok"] is True
    verify = _load(out / "J1_verify_input_schema.json")
    assert verify["header_match"] is True
    assert verify["sha256"] == _sha(csv_path)
    assert not (out / "orders.csv").exists()
    aggregate = _load(out / "J2_temporal_aggregate.json")
    assert aggregate["grain"] == "week"
    assert aggregate["measures"] == ["revenue"]
    assert aggregate["time_column"] == "invoice_date"
    assert sum(Decimal(bucket["sums"]["revenue"]) for bucket in aggregate["buckets"]) == Decimal("14.00")
    sla = _load(out / "J3_sla_breach_list.json")
    assert {(item["key"], item["type"]) for item in sla["breaches"]} == {
        ("I-1", "missing_end"),
        ("I-2", "end_before_start"),
    }
    pack = _load(out / "J4_evidence_pack.json")
    assert pack["covers"] == ["J1", "J2", "J3"]
    assert pack["roles"] == ["identifier", "measure"]
    assert "expected_sha256" not in pack
    assert "generator_seed" not in pack
    assert not (tmp_path / "dispatch.json").exists()
    assert not (out / "worker_jobs.py").exists()


def test_invoices_goal_executes_a_different_derived_set(tmp_path):
    csv_path = tmp_path / "invoices.csv"
    csv_path.write_text(
        "invoice_id,invoice_date,revenue,payment_status\n"
        "I-1,2026-03-02,10.00,paid\n"
        "I-2,2026-03-15,5.00,paid\n"
        "I-3,2026-04-01,-1.00,\n",
        encoding="utf-8",
    )
    goal = {
        "statement": (
            "Frozen invoices: monthly summary, an anomaly list, "
            "and an independently verifiable evidence pack."
        ),
        "schema": {"columns": ["invoice_id", "invoice_date", "revenue", "payment_status"]},
    }
    out = tmp_path / "out"
    result = run_goal(goal, csv_path, out)
    assert result["ok"] is True
    dispatch = _load(out / "derived_dispatch.json")
    live = get_decomposer().decompose(goal)
    assert [job["kind"] for job in dispatch["jobs"]] == [job["kind"] for job in live]
    assert [job["kind"] for job in live] == [
        "verify_input_schema",
        "temporal_aggregate",
        "anomaly_list",
        "evidence_pack",
    ]
    assert "sla_breach_list" not in [job["kind"] for job in live]
    assert "backlog_aging" not in [job["kind"] for job in live]
    assert HISTORICAL_TITLES.isdisjoint(job["title"] for job in live)
    aggregate = _load(out / "J2_temporal_aggregate.json")
    assert aggregate["grain"] == "month"
    assert aggregate["time_column"] == "invoice_date"
    assert aggregate["measures"] == ["revenue"]
    sums = {bucket["period"]: Decimal(bucket["sums"]["revenue"]) for bucket in aggregate["buckets"]}
    assert sums == {"2026-03": Decimal("15.00"), "2026-04": Decimal("-1.00")}
    anomalies = _load(out / "J3_anomaly_list.json")
    assert {(item["key"], item["column"], item["type"]) for item in anomalies["anomalies"]} == {
        ("I-3", "payment_status", "missing"),
        ("I-3", "revenue", "negative"),
    }
    ticket_titles = {job["title"] for job in get_decomposer().decompose(_goal())}
    assert ticket_titles.isdisjoint(job["title"] for job in live)


def test_aging_without_a_close_column_uses_the_open_timestamps(tmp_path):
    csv_path = tmp_path / "open.csv"
    csv_path.write_text(
        "ticket_id,opened_at\n"
        "A,2026-01-01T00:00:00Z\n"
        "B,2026-01-03T00:00:00Z\n",
        encoding="utf-8",
    )
    jobs = [
        {
            "job_id": "J1",
            "title": "not-read",
            "kind": "verify_input_schema",
            "status": "PENDING",
            "inputs": {"key": "ticket_id", "columns": ["ticket_id", "opened_at"]},
        },
        {
            "job_id": "J2",
            "title": "not-read",
            "kind": "backlog_aging",
            "status": "PENDING",
            "inputs": {"grain": None, "open": "opened_at", "close": None},
        },
    ]
    out = tmp_path / "out"
    assert execute_jobs(jobs, csv_path, out)["ok"] is True
    payload = _load(out / "J2_backlog_aging.json")
    assert payload["as_of"] == "2026-01-03T00:00:00Z"
    assert payload["close"] is None
    by_key = {item["key"]: item["age_seconds"] for item in payload["backlog"]}
    assert by_key == {"A": 172800, "B": 0}
    assert payload["buckets"] == [{
        "period": "all",
        "opened": 2,
        "still_open": 2,
        "closed": 0,
        "open_age_seconds_sum": 172800,
        "closed_age_seconds_sum": 0,
    }]


def test_no_rule_match_does_not_invent_the_historical_job_list(tmp_path):
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("order_id\nA\n", encoding="utf-8")
    goal = {"statement": "hello", "schema": {"columns": ["order_id"]}}
    out = tmp_path / "out"
    result = run_goal(goal, csv_path, out)
    assert result["ok"] is False
    assert result["error"] == "no_jobs_derived"
    dispatch = _load(out / "derived_dispatch.json")
    assert dispatch["jobs"] == []
    assert dispatch["ok"] is False
    assert dispatch["claim_boundary"] == CLAIM
    assert sorted(path.name for path in out.iterdir()) == ["derived_dispatch.json", "worklog.json"]


def test_invalid_goal_writes_nothing(tmp_path):
    out = tmp_path / "out"
    result = run_goal(
        {"statement": 5, "schema": {"columns": ["ticket_id"]}},
        tmp_path / "missing.csv",
        out,
    )
    assert result["ok"] is False
    assert result["error"] == "invalid_goal"
    assert not out.exists()


def test_historical_task_ids_are_refused_and_t1_bytes_stay_put(tmp_path):
    before = _tree_hashes(T1)
    assert before
    assert "deliverables" not in {path.name for path in T1.iterdir()}
    code = worker_main(["--task-id", "DS-T1-20261108", "--out", str(tmp_path / "t1-out")])
    assert code == 2
    assert _tree_hashes(T1) == before
    assert not (T1 / "deliverables").exists()
    assert not (tmp_path / "t1-out").exists()

    t2 = ROOT / "task_inbox" / "DS-T2-20261110"
    assert not t2.exists()
    assert worker_main(["--task-id", "DS-T2-20261110"]) == 2
    assert not t2.exists()

    refused = run_card(T1, tmp_path / "from-card")
    assert refused["ok"] is False
    assert refused["error"] == "refusing_historical_observation_task"
    assert _tree_hashes(T1) == before
    assert not (tmp_path / "from-card").exists()


def test_cli_runs_the_fixture_without_a_dispatch_file(tmp_path):
    card = _copy_fixture(tmp_path)
    out = tmp_path / "out"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "worker_run_task.py"),
            "--card",
            str(card),
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    printed = json.loads(completed.stdout)
    assert printed["ok"] is True
    assert printed["claim_boundary"] == CLAIM
    dispatch = _load(out / "derived_dispatch.json")
    assert [job["kind"] for job in dispatch["jobs"]] == [
        job["kind"] for job in get_decomposer().decompose(_load(card / "goal.json"))
    ]
    assert not (card / "dispatch.json").exists()
    assert worker_main(["--card", str(card), "--task-id", "anything"]) == 2


def test_runner_source_does_not_hardcode_the_historical_job_list():
    sources = [
        (ROOT / "control_plane" / "derived_worker.py").read_text(encoding="utf-8"),
        (ROOT / "scripts" / "worker_run_task.py").read_text(encoding="utf-8"),
    ]
    # ``anomaly_list`` is also a derived kind, so the executor names it.
    # The other three historical titles are not kinds and must not be hardcoded.
    banned_titles = HISTORICAL_TITLES - {"anomaly_list"}
    for source in sources:
        for title in banned_titles:
            assert title not in source
    script = sources[1]
    assert "decompose" in script
    assert "importlib" not in script
    assert "worker_jobs.py" in script
    assert "does not import" in script


def test_doc_keeps_the_claim_boundary_and_does_not_grant_l2():
    note = (ROOT / "docs" / "l2-derive-execute.md").read_text(encoding="utf-8")
    for phrase in (
        "CONDITIONAL",
        "not granted",
        "not accepted",
        "NOT ACCEPTED",
        "NOT STARTED",
        "T3 run submitted for observation-track acceptance",
        "Observation-track acceptance is not claimed",
        "derived_dispatch.json",
        "does not read a pre-written `dispatch.json`",
        "does not import `worker_jobs.py`",
    ):
        assert phrase in note
    for banned in (
        "L2 is granted",
        "L2 accepted",
        "7×24 is accepted",
        "72h clock is started",
        "production 7×24 is accepted",
    ):
        assert banned not in note
    evidence = (ROOT / "docs" / "l2-derivation-evidence.md").read_text(encoding="utf-8")
    assert "returned []" in evidence
    assert "generate_or_verify_orders_csv" in evidence
