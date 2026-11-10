"""Chinese loan goal: derive, execute, and keep the job list off a dispatch file.

The received card is DS-T3-20261111. These tests lock four claims:
- the same loan schema and the same intents produce the same jobs in
  Chinese and in English, and a task id does not choose them
- a different schema produces a different job set
- summary.json and overdue.json match an independent pass over the rows
- a pre-written dispatch.json and worker_jobs.py are not the job source

This file does not grant L2. Production 7×24 is NOT ACCEPTED.
The L2-2 72h clock is NOT STARTED.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.derived_worker import run_card
from control_plane.task_decomposer import get_decomposer, project_plan
from scripts.worker_run_task import main as worker_main


CARD = ROOT / "task_inbox" / "DS-T3-20261111"
T1 = ROOT / "task_inbox" / "DS-T1-20261108"
ZH_GOAL = "为图书馆借阅数据生成「借阅运营汇总 + 逾期清单 + 可独立核验的证据包」。"
EN_GOAL = (
    "Library loans: an operating summary, an overdue list, "
    "and an independently verifiable evidence pack."
)
ORDERS_ZH = "月度经营汇总、异常清单和证据包"
LOAN_COLUMNS = [
    "loan_id", "book_id", "member_id", "borrowed_date",
    "loan_days", "returned_date", "category",
]
ORDER_COLUMNS = [
    "order_id", "order_date", "amount", "status", "customer_id", "channel",
]
FROZEN_SHA = "429b3287c37d07c350926e53bacc0f475f77dabd94dc1eb3bc1f703776ffdf51"
FROZEN_BYTES = 165090
FROZEN_LINES = 4001
T1_HASHES = {
    "TASK.md": "7bdbd16bbc7714b2ba669b029635bdf48e270505936e36441d7cd678cc81983b",
    "dispatch.json": "7647386e4b4126569d858547c7db6e0b49b9521edd1f01fe1f45bbc085d21eae",
    "worker_jobs.py": "0681e5926a09d4a4c88c68e62718f50eae31966fe1491a3d4dc5b7f4e9f8f634",
}
HISTORICAL_TITLES = {
    "generate_or_verify_orders_csv",
    "monthly_summary",
    "anomaly_list",
    "evidence_pack_manifest",
}
REFERENCE = "2026-10-31"


def _loan_goal(statement: str = ZH_GOAL, columns: list[str] | None = None, reference: str | None = REFERENCE) -> dict:
    goal = {
        "statement": statement,
        "schema": {"columns": list(columns if columns is not None else LOAN_COLUMNS)},
    }
    if reference is not None:
        goal["reference_date"] = reference
    return goal


def _titles(jobs: list[dict]) -> list[str]:
    return [job["title"] for job in jobs]


def _kinds(jobs: list[dict]) -> list[str]:
    return [job["kind"] for job in jobs]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, str]]:
    import csv
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _independent(rows: list[dict[str, str]], reference: str) -> tuple[dict, list[dict]]:
    ref = date.fromisoformat(reference)
    total = len(rows)
    returned = 0
    overdue_ids: list[int] = []
    by_category: dict[str, int] = {}
    by_month: dict[str, int] = {}
    members: dict[str, int] = {}
    for row in rows:
        if row["returned_date"].strip():
            returned += 1
        else:
            borrowed = date.fromisoformat(row["borrowed_date"])
            if (ref - borrowed).days > int(row["loan_days"]):
                overdue_ids.append(int(row["loan_id"]))
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1
        month = row["borrowed_date"][:7]
        by_month[month] = by_month.get(month, 0) + 1
        members[row["member_id"]] = members.get(row["member_id"], 0) + 1
    ranked = sorted(members.items(), key=lambda item: (-item[1], item[0]))[:10]
    overdue_ids.sort()
    summary = {
        "total_loans": total,
        "total_returned": returned,
        "total_outstanding": total - returned,
        "total_overdue": len(overdue_ids),
        "by_category": {name: by_category[name] for name in sorted(by_category)},
        "by_month": {name: by_month[name] for name in sorted(by_month)},
        "top10_members": [{"member_id": member_id, "loans": count} for member_id, count in ranked],
    }
    return summary, [{"loan_id": loan_id} for loan_id in overdue_ids]


def _write_small_card(directory: Path, reference: str = REFERENCE, statement: str = ZH_GOAL) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / "loans.csv"
    csv_path.write_text(
        "loan_id,book_id,member_id,borrowed_date,loan_days,returned_date,category\n"
        "1,B001,M0001,2026-10-01,30,,lit\n"
        "2,B001,M0001,2026-10-01,29,,lit\n"
        "3,B002,M0002,2026-09-01,14,2026-11-15,sci\n"
        "4,B003,M0001,2026-10-17,14,,tech\n"
        "5,B004,M0003,2026-01-15,21,2026-02-01,hist\n"
        "6,B005,M0002,2026-08-01,30,,hist\n",
        encoding="utf-8",
    )
    goal = _loan_goal(statement, reference=reference)
    goal["input"] = "loans.csv"
    goal["observation_card"] = False
    (directory / "goal.json").write_text(json.dumps(goal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return directory


def test_chinese_and_english_loan_goals_derive_the_same_jobs():
    decomposer = get_decomposer()
    chinese = decomposer.decompose(_loan_goal(ZH_GOAL))
    english = decomposer.decompose(_loan_goal(EN_GOAL))
    assert chinese == english
    assert _kinds(chinese) == [
        "verify_input_schema",
        "loan_operations_summary",
        "overdue_list",
        "evidence_pack",
    ]
    assert _titles(chinese) == [
        "verify_input_schema_keyed_by_loan_id",
        "summarize_loan_id_by_category_and_month_of_borrowed_date_top_member_id",
        "list_overdue_loan_id_from_borrowed_date_plus_loan_days_until_returned_date",
        "assemble_evidence_pack_over_calendar_date_dimension_duration_identifier",
    ]
    assert HISTORICAL_TITLES.isdisjoint(_titles(chinese))
    assert chinese[1]["inputs"]["reference_date"] == REFERENCE
    assert chinese[1]["inputs"]["member"] == "member_id"
    assert chinese[1]["inputs"]["category"] == "category"
    assert chinese[2]["inputs"]["duration"] == "loan_days"
    assert chinese[2]["inputs"]["end"] == "returned_date"
    assert chinese[-1]["inputs"]["covers"] == ["J1", "J2", "J3"]
    assert len(chinese) >= 2


def test_task_id_and_fixture_name_do_not_change_the_loan_jobs():
    decomposer = get_decomposer()
    plain = decomposer.decompose(_loan_goal())
    labeled = _loan_goal()
    labeled["task_id"] = "DS-T3-20261111"
    labeled["fixture_name"] = "loans.csv"
    labeled["schema"]["name"] = "loans.csv"
    other = _loan_goal()
    other["task_id"] = "DS-T1-20261108"
    other["fixture"] = "orders.csv"
    assert decomposer.decompose(labeled) == plain
    assert decomposer.decompose(other) == plain


def test_reference_date_changes_job_inputs_not_the_titles():
    decomposer = get_decomposer()
    october = decomposer.decompose(_loan_goal(reference="2026-10-31"))
    september = decomposer.decompose(_loan_goal(reference="2026-09-30"))
    assert _titles(october) == _titles(september)
    assert october[2]["inputs"]["reference_date"] == "2026-10-31"
    assert september[2]["inputs"]["reference_date"] == "2026-09-30"
    assert october != september


def test_chinese_orders_statement_follows_the_orders_schema():
    jobs = get_decomposer().decompose(_loan_goal(ORDERS_ZH, ORDER_COLUMNS, reference=None))
    assert _titles(jobs) == [
        "verify_input_schema_keyed_by_order_id",
        "aggregate_amount_by_month_of_order_date",
        "list_anomalies_on_status_amount",
        "assemble_evidence_pack_over_calendar_date_dimension_identifier_measure_status",
    ]
    assert "loan_operations_summary" not in _kinds(jobs)
    assert "overdue_list" not in _kinds(jobs)
    assert HISTORICAL_TITLES.isdisjoint(_titles(jobs))
    loan_titles = set(_titles(get_decomposer().decompose(_loan_goal())))
    assert loan_titles.isdisjoint(_titles(jobs))


def test_a_narrower_loan_schema_drops_the_summary_and_keeps_overdue():
    columns = ["loan_id", "borrowed_date", "loan_days", "returned_date"]
    jobs = get_decomposer().decompose(_loan_goal(ZH_GOAL, columns))
    assert _kinds(jobs) == ["verify_input_schema", "overdue_list", "evidence_pack"]
    assert "loan_operations_summary" not in _kinds(jobs)


def test_dropping_the_overdue_phrase_drops_only_that_job():
    statement = "为图书馆借阅数据生成「借阅运营汇总 + 可独立核验的证据包」。"
    jobs = get_decomposer().decompose(_loan_goal(statement))
    assert _kinds(jobs) == ["verify_input_schema", "loan_operations_summary", "evidence_pack"]


def test_renamed_loan_columns_compose_different_titles():
    columns = ["copy_id", "patron_id", "borrow_date", "term_days", "return_date", "genre"]
    jobs = get_decomposer().decompose(_loan_goal(EN_GOAL, columns))
    assert _titles(jobs) == [
        "verify_input_schema_keyed_by_copy_id",
        "summarize_copy_id_by_genre_and_month_of_borrow_date_top_patron_id",
        "list_overdue_copy_id_from_borrow_date_plus_term_days_until_return_date",
        "assemble_evidence_pack_over_calendar_date_dimension_duration_identifier",
    ]
    canonical = get_decomposer().decompose(_loan_goal())
    assert jobs != canonical
    assert set(_titles(jobs)) != set(_titles(canonical))
    assert set(_titles(jobs)) - set(_titles(canonical)) == {
        "verify_input_schema_keyed_by_copy_id",
        "summarize_copy_id_by_genre_and_month_of_borrow_date_top_patron_id",
        "list_overdue_copy_id_from_borrow_date_plus_term_days_until_return_date",
    }
    assert jobs[1]["inputs"]["member"] == "patron_id"
    assert jobs[2]["inputs"]["duration"] == "term_days"


def test_integer_loan_days_stay_a_duration_and_are_not_summed_as_a_measure():
    jobs = get_decomposer().decompose({
        "statement": EN_GOAL,
        "reference_date": REFERENCE,
        "schema": {"columns": [
            {"name": "loan_id"},
            {"name": "member_id"},
            {"name": "borrowed_date"},
            {"name": "loan_days", "type": "integer"},
            {"name": "returned_date"},
            {"name": "category"},
        ]},
    })
    assert "temporal_aggregate" not in _kinds(jobs)
    assert jobs[1]["kind"] == "loan_operations_summary"
    assert jobs[1]["inputs"]["duration"] == "loan_days"


def test_plan_projection_follows_the_derived_jobs_and_changes_with_the_schema():
    full = get_decomposer().decompose(_loan_goal())
    plan = project_plan(_loan_goal(), full, "loans.csv")
    assert set(plan) == {"goal", "derived_tasks", "why", "alternatives_considered"}
    assert plan["goal"] == ZH_GOAL
    assert [task["task_id"] for task in plan["derived_tasks"]] == [job["job_id"] for job in full]
    assert all(task["inputs"] == ["loans.csv"] for task in plan["derived_tasks"])
    assert plan["derived_tasks"][1]["outputs"] == ["summary.json"]
    assert plan["derived_tasks"][2]["outputs"] == ["overdue.json"]
    assert "逾期" in plan["why"]
    assert "汇总" in plan["why"]
    assert plan["alternatives_considered"]
    assert any("不按月" in item or "不单列异常" in item for item in plan["alternatives_considered"])

    narrow = get_decomposer().decompose(_loan_goal(columns=["loan_id", "borrowed_date", "loan_days", "returned_date"]))
    other = project_plan(
        _loan_goal(columns=["loan_id", "borrowed_date", "loan_days", "returned_date"]),
        narrow,
        "loans.csv",
    )
    assert [task["task_id"] for task in other["derived_tasks"]] != [task["task_id"] for task in plan["derived_tasks"]] or _kinds(narrow) != _kinds(full)
    assert _kinds(narrow) != _kinds(full)
    assert other["why"] != plan["why"]
    assert other["alternatives_considered"] != plan["alternatives_considered"]


def test_sources_do_not_embed_the_card_id_or_the_frozen_fingerprint():
    banned = [
        "DS-T3-20261111",
        "2026-10-31",
        FROZEN_SHA,
        ZH_GOAL,
    ]
    for relative in (
        "control_plane/task_decomposer.py",
        "control_plane/derived_worker.py",
        "scripts/worker_run_task.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        for item in banned:
            assert item not in source
    runner = (ROOT / "scripts" / "worker_run_task.py").read_text(encoding="utf-8")
    assert "does not import" in runner
    assert "dispatch.json" in runner


def test_small_card_matches_an_independent_boundary_check(tmp_path):
    card = _write_small_card(tmp_path / "card")
    out = tmp_path / "out"
    result = run_card(card, out)
    assert result["ok"] is True
    assert result["used_preauthored_dispatch"] is False
    assert result["used_worker_jobs_py"] is False
    expected, items = _independent(_rows(card / "loans.csv"), REFERENCE)
    assert expected == {
        "total_loans": 6,
        "total_returned": 2,
        "total_outstanding": 4,
        "total_overdue": 2,
        "by_category": {"hist": 2, "lit": 2, "sci": 1, "tech": 1},
        "by_month": {"2026-01": 1, "2026-08": 1, "2026-09": 1, "2026-10": 3},
        "top10_members": [
            {"member_id": "M0001", "loans": 3},
            {"member_id": "M0002", "loans": 2},
            {"member_id": "M0003", "loans": 1},
        ],
    }
    assert items == [{"loan_id": 2}, {"loan_id": 6}]
    assert _load(out / "summary.json") == expected
    assert _load(out / "overdue.json") == {"items": items}
    assert _load(out / "plan.json")["goal"] == ZH_GOAL
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "This run is not an observation card." in report
    assert "L2 is not granted" in report
    assert "NOT ACCEPTED" in report
    assert "NOT STARTED" in report
    dispatch = _load(out / "derived_dispatch.json")
    assert dispatch["read_as_job_source"] is False
    assert dispatch["produced_by"] == "control_plane.task_decomposer.TaskDecomposer.decompose"
    assert [job["title"] for job in dispatch["jobs"]] == _titles(get_decomposer().decompose(_load(card / "goal.json")))
    assert not (card / "dispatch.json").exists()
    assert not (card / "worker_jobs.py").exists()


def test_a_different_reference_date_changes_the_overdue_set(tmp_path):
    early = _write_small_card(tmp_path / "early", reference="2026-10-02")
    out = tmp_path / "out"
    assert run_card(early, out)["ok"] is True
    expected, items = _independent(_rows(early / "loans.csv"), "2026-10-02")
    assert items == [{"loan_id": 6}]
    assert _load(out / "overdue.json")["items"] == items
    assert _load(out / "summary.json")["total_overdue"] == 1
    assert _load(out / "summary.json")["total_outstanding"] == expected["total_outstanding"]


def test_poisoned_dispatch_and_worker_jobs_do_not_supply_the_loan_jobs(tmp_path):
    card = _write_small_card(tmp_path / "card")
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
    goal["task_id"] = "DS-T3-20261111"
    (card / "goal.json").write_text(json.dumps(goal, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    result = run_card(card, out)
    assert result["ok"] is True
    assert not (card / "decoy_ran.txt").exists()
    dispatch = _load(out / "derived_dispatch.json")
    assert HISTORICAL_TITLES.isdisjoint(job["title"] for job in dispatch["jobs"])
    assert [job["kind"] for job in dispatch["jobs"]] == _kinds(get_decomposer().decompose(goal))
    assert "task_id" in dispatch["ignored_keys"]
    assert _load(out / "manifest.json")["task_id"] == "DS-T3-20261111"
    assert _load(out / "manifest.json")["submission"]["observation_track_acceptance"] is False
    assert _load(out / "manifest.json")["submission"]["l2_granted"] is False
    assert _load(out / "manifest.json")["submission"]["production_7x24"] == "NOT ACCEPTED"
    assert _load(out / "manifest.json")["submission"]["l2_2_72h_clock"] == "NOT STARTED"


def test_received_card_has_no_handwritten_dispatch_and_matches_the_freeze():
    assert CARD.is_dir()
    assert not (CARD / "dispatch.json").exists()
    assert not (CARD / "worker_jobs.py").exists()
    data = (CARD / "loans.csv").read_bytes()
    assert len(data) == FROZEN_BYTES
    assert hashlib.sha256(data).hexdigest() == FROZEN_SHA
    assert data.decode("utf-8").count("\n") == FROZEN_LINES
    goal = _load(CARD / "goal.json")
    assert goal["statement"] == ZH_GOAL
    assert goal["task_id"] == "DS-T3-20261111"
    assert goal["reference_date"] == REFERENCE
    assert goal["input"] == "loans.csv"
    assert "jobs" not in goal
    names = [column["name"] for column in goal["schema"]["columns"]]
    assert names == LOAN_COLUMNS
    for name, digest in T1_HASHES.items():
        assert hashlib.sha256((T1 / name).read_bytes()).hexdigest() == digest
    assert not (ROOT / "task_inbox" / "DS-T2-20261110").exists()


def test_received_card_run_matches_an_independent_recompute_and_the_checked_in_outputs(tmp_path):
    before = {
        path.relative_to(CARD): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in CARD.rglob("*")
        if path.is_file() and "deliverables" not in path.parts
    }
    out = tmp_path / "out"
    code = worker_main(["--task-id", "DS-T3-20261111", "--out", str(out)])
    assert code == 0
    after = {
        path.relative_to(CARD): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in CARD.rglob("*")
        if path.is_file() and "deliverables" not in path.parts
    }
    assert after == before
    for name, digest in T1_HASHES.items():
        assert hashlib.sha256((T1 / name).read_bytes()).hexdigest() == digest

    expected, items = _independent(_rows(CARD / "loans.csv"), REFERENCE)
    summary = _load(out / "summary.json")
    overdue = _load(out / "overdue.json")
    assert summary == expected
    assert overdue == {"items": items}
    assert summary["total_returned"] + summary["total_outstanding"] == summary["total_loans"]
    assert summary["total_overdue"] <= summary["total_outstanding"]
    assert sum(summary["by_category"].values()) == summary["total_loans"]
    assert sum(summary["by_month"].values()) == summary["total_loans"]
    assert summary["total_overdue"] == len(overdue["items"])
    assert [item["loan_id"] for item in overdue["items"]] == sorted(item["loan_id"] for item in overdue["items"])

    goal = _load(CARD / "goal.json")
    dispatch = _load(out / "derived_dispatch.json")
    live = get_decomposer().decompose(goal)
    assert [job["title"] for job in dispatch["jobs"]] == _titles(live)
    assert [job["inputs"] for job in dispatch["jobs"]] == [job["inputs"] for job in live]
    assert dispatch["read_as_job_source"] is False
    assert dispatch["used_worker_jobs_py"] is False
    assert "task_id" in dispatch["ignored_keys"]
    assert HISTORICAL_TITLES.isdisjoint(job["title"] for job in live)

    plan = _load(out / "plan.json")
    assert plan["goal"] == ZH_GOAL
    assert len(plan["derived_tasks"]) >= 2
    assert [task["task_id"] for task in plan["derived_tasks"]] == [job["job_id"] for job in live]
    assert all(task["inputs"] == ["loans.csv"] for task in plan["derived_tasks"])
    assert plan["why"]
    assert len(plan["alternatives_considered"]) >= 2

    manifest = _load(out / "manifest.json")
    assert manifest["task_id"] == "DS-T3-20261111"
    assert manifest["input"]["sha256"] == FROZEN_SHA
    assert manifest["input"]["bytes"] == FROZEN_BYTES
    assert manifest["input"]["lines"] == FROZEN_LINES
    assert manifest["submission"]["submitted_for_observation"] is True
    assert manifest["submission"]["observation_track_acceptance"] is False
    assert manifest["submission"]["l2_granted"] is False
    assert manifest["submission"]["production_7x24"] == "NOT ACCEPTED"
    assert manifest["submission"]["l2_2_72h_clock"] == "NOT STARTED"
    assert manifest["derivation"]["used_preauthored_dispatch"] is False
    assert manifest["deliverables"]["summary.json"]["sha256"] == hashlib.sha256((out / "summary.json").read_bytes()).hexdigest()
    assert manifest["deliverables"]["overdue.json"]["sha256"] == hashlib.sha256((out / "overdue.json").read_bytes()).hexdigest()
    assert "worklog.json" not in manifest["deliverables"]
    assert "manifest.json" not in manifest["deliverables"]

    report = (out / "report.md").read_text(encoding="utf-8")
    for phrase in (
        "This is a T3 run submitted for observation-track acceptance.",
        "Observation-track acceptance is not claimed.",
        "L2 is not granted and not accepted.",
        "Production 7×24 is NOT ACCEPTED.",
        "The L2-2 72h clock is NOT STARTED.",
        "No pre-written `dispatch.json` was read.",
        "`worker_jobs.py` was not imported.",
    ):
        assert phrase in report
    for banned in ("L2 is granted", "L2 accepted", "72h clock is started", "7×24 is accepted"):
        assert banned not in report

    committed = CARD / "deliverables"
    fresh_names = sorted(path.name for path in out.iterdir())
    committed_names = sorted(path.name for path in committed.iterdir())
    assert fresh_names == committed_names
    for name in fresh_names:
        if name == "worklog.json":
            continue
        assert (out / name).read_bytes() == (committed / name).read_bytes()
    worklog = _load(committed / "worklog.json")
    assert worklog["ok"] is True
    assert worklog["used_preauthored_dispatch"] is False
    assert worklog["used_worker_jobs_py"] is False
    assert worklog["path"] == "derive_then_execute"
