"""Fingerprint and rule checks for the DS-T1-20261108 worker jobs."""

from __future__ import annotations

import csv
import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "task_inbox" / "DS-T1-20261108" / "worker_jobs.py"
    spec = importlib.util.spec_from_file_location("ds_t1_worker_jobs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


JOBS = _load()


def test_frozen_generator_fingerprint():
    raw = JOBS.render_orders_csv().encode("utf-8")
    info = JOBS.fingerprint(raw)
    assert info["match_expected"] is True
    assert info["sha256"] == JOBS.EXPECTED_SHA
    assert info["bytes"] == 237705
    assert info["lines"] == 6001


def test_summary_balances_and_top10_order():
    text = JOBS.render_orders_csv()
    rows = list(csv.DictReader(text.splitlines()))
    summary = JOBS.summarize(rows)
    assert summary["total_orders"] == 6000
    assert set(summary["by_month"]) == {f"2026-{m:02d}" for m in range(1, 10)}
    total = Decimal(summary["total_amount"])
    assert sum(Decimal(bucket["amount"]) for bucket in summary["by_month"].values()) == total
    assert sum(Decimal(bucket["amount"]) for bucket in summary["by_status"].values()) == total
    assert sum(Decimal(bucket["amount"]) for bucket in summary["by_channel"].values()) == total
    assert sum(bucket["orders"] for bucket in summary["by_month"].values()) == 6000
    top = summary["top10_customers"]
    assert len(top) == 10
    amounts = [Decimal(item["amount"]) for item in top]
    assert amounts == sorted(amounts, reverse=True)
    for left, right in zip(top, top[1:]):
        if left["amount"] == right["amount"]:
            assert left["customer_id"] < right["customer_id"]


def test_anomaly_rules_and_sort():
    rows = [
        {"order_id": "2", "customer_id": "C0002", "order_date": "2026-01-02", "amount": "9.99", "status": "paid", "channel": "web"},
        {"order_id": "2", "customer_id": "C0002", "order_date": "2026-01-02", "amount": "10.00", "status": "paid", "channel": "web"},
        {"order_id": "3", "customer_id": "C0003", "order_date": "2026-10-01", "amount": "1000.00", "status": "cancelled", "channel": "app"},
        {"order_id": "4", "customer_id": "C0004", "order_date": "not-a-date", "amount": "1000.01", "status": "cancelled", "channel": "store"},
        {"order_id": "5", "customer_id": "C0005", "order_date": "2026-09-30", "amount": "10.00", "status": "cancelled", "channel": "web"},
    ]
    found = {(item["rule"], item["order_id"]) for item in JOBS.find_anomalies(rows)}
    assert ("A1", 2) in found
    assert ("A3", 2) in found
    assert ("A2", 3) not in found  # 1000.00 is not greater than 1000.00
    assert ("A4", 3) in found
    assert ("A2", 4) in found
    assert ("A4", 4) in found
    assert ("A1", 5) not in found
    assert ("A2", 5) not in found
    assert ("A4", 5) not in found
    ordered = JOBS.find_anomalies(rows)
    assert ordered == sorted(ordered, key=lambda item: (item["order_id"], item["rule"]))
    assert date.fromisoformat("2026-09-30") == JOBS.DATE_MAX


def test_run_writes_contract_files(tmp_path: Path):
    inbox = tmp_path / "task_inbox" / "DS-T1-20261108"
    inbox.mkdir(parents=True)
    dispatch = {
        "task_id": "DS-T1-20261108",
        "jobs": [
            {"job_id": "J1", "title": "generate_or_verify_orders_csv", "status": "PENDING"},
            {"job_id": "J2", "title": "monthly_summary", "status": "PENDING"},
            {"job_id": "J3", "title": "anomaly_list", "status": "PENDING"},
            {"job_id": "J4", "title": "evidence_pack_manifest", "status": "PENDING"},
        ],
        "network": False,
        "paid": False,
    }
    (inbox / "dispatch.json").write_text(json.dumps(dispatch), encoding="utf-8")
    out = inbox / "deliverables"
    result = JOBS.run(inbox=inbox, out=out, task_id="DS-T1-20261108")
    assert result["ok"] is True
    assert result["fingerprint_match"] is True
    for name in ("summary.json", "anomalies.json", "report.md", "manifest.json"):
        assert (out / name).is_file()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["task_id"] == "DS-T1-20261108"
    assert manifest["component_version"] == "ds-t1-worker-1"
    assert manifest["input"]["sha256"] == JOBS.EXPECTED_SHA
    assert [item["path"].split("/")[-1] for item in manifest["outputs"]] == [
        "summary.json",
        "anomalies.json",
        "report.md",
    ]
    saved = json.loads((inbox / "dispatch.json").read_text(encoding="utf-8"))
    assert saved["fingerprint_match"] is True
    assert [job["status"] for job in saved["jobs"]] == ["DONE", "DONE", "DONE", "DONE"]
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "生产 7×24 **未验收**" in report
    assert "BLOCKED" not in report
