"""Worker jobs for DS-T1-20261108 — invoked only via scripts/worker_run_task.py.

Generator is the frozen script from the observation-track card on
AIStudioOS-Grok issue #9 (TASK ID DS-T1-20261108). Do not retune it to
chase the fingerprint: a mismatch is BLOCKED.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

EXPECTED_SHA = "633aded091b1da111f4c3c9c378c975d3bdddf17e85a0fd3b001c7e4ddbf7ffe"
EXPECTED_BYTES = 237705
EXPECTED_LINES = 6001  # header + 6000 data rows, LF, trailing newline
SEED = 20261108
COMPONENT_VERSION = "ds-t1-worker-1"
DATE_MIN = date(2026, 1, 1)
DATE_MAX = date(2026, 9, 30)  # 2026-01-01 + randrange(0, 273) inclusive
MONTHS = tuple(f"2026-{m:02d}" for m in range(1, 10))
STATUSES = ("paid", "pending", "refunded", "cancelled")
CHANNELS = ("web", "app", "store")
CENT = Decimal("0.01")
JOBS = (
    ("J1", "generate_or_verify_orders_csv"),
    ("J2", "monthly_summary"),
    ("J3", "anomaly_list"),
    ("J4", "evidence_pack_manifest"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT):.2f}"


def repo_root(inbox: Path) -> Path:
    return inbox.parent.parent


def relpath(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def render_orders_csv() -> str:
    """Byte-level copy of the frozen observation-track generator."""
    import random

    rng = random.Random(SEED)
    start = date(2026, 1, 1)
    rows = []
    for i in range(1, 6001):
        cid = "C%04d" % rng.randrange(1, 801)
        off = rng.randrange(0, 273)
        cents = rng.randrange(500, 200001)
        u = rng.randrange(100)
        status = "paid" if u < 70 else "pending" if u < 90 else "refunded" if u < 96 else "cancelled"
        v = rng.randrange(100)
        channel = "web" if v < 50 else "app" if v < 85 else "store"
        rows.append(
            (
                i,
                cid,
                (start + timedelta(days=off)).isoformat(),
                "%d.%02d" % (cents // 100, cents % 100),
                status,
                channel,
            )
        )
    return (
        "order_id,customer_id,order_date,amount,status,channel\n"
        + "\n".join(",".join(map(str, r)) for r in rows)
        + "\n"
    )


def fingerprint(raw: bytes) -> dict:
    newline_count = raw.count(b"\n")
    line_count = len(raw.splitlines())
    digest = sha256_bytes(raw)
    match = (
        digest == EXPECTED_SHA
        and len(raw) == EXPECTED_BYTES
        and line_count == EXPECTED_LINES
        and newline_count == EXPECTED_LINES
        and not raw.startswith(b"\xef\xbb\xbf")
    )
    return {
        "sha256": digest,
        "bytes": len(raw),
        "lines": line_count,
        "newlines": newline_count,
        "match_expected": match,
        "expected_sha256": EXPECTED_SHA,
        "expected_bytes": EXPECTED_BYTES,
        "expected_lines": EXPECTED_LINES,
    }


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _bucket_template(keys: tuple[str, ...]) -> dict[str, dict[str, Decimal | int]]:
    return {key: {"orders": 0, "amount": Decimal("0")} for key in keys}


def _freeze_buckets(buckets: dict[str, dict[str, Decimal | int]], preferred: tuple[str, ...]) -> dict[str, dict]:
    ordered = [key for key in preferred if key in buckets]
    ordered.extend(sorted(key for key in buckets if key not in preferred))
    return {
        key: {"orders": int(buckets[key]["orders"]), "amount": money(buckets[key]["amount"])}
        for key in ordered
    }


def summarize(rows: list[dict[str, str]]) -> dict:
    """Gross amount column. Status is not netted out; see by_status."""
    total = Decimal("0")
    by_month = _bucket_template(MONTHS)
    by_status = _bucket_template(STATUSES)
    by_channel = _bucket_template(CHANNELS)
    customers: dict[str, dict[str, Decimal | int]] = {}

    for row in rows:
        amount = Decimal(row["amount"])
        month = row["order_date"][:7]
        status = row["status"]
        channel = row["channel"]
        customer = row["customer_id"]
        total += amount
        for bucket, key in (
            (by_month, month),
            (by_status, status),
            (by_channel, channel),
        ):
            slot = bucket.setdefault(key, {"orders": 0, "amount": Decimal("0")})
            slot["orders"] = int(slot["orders"]) + 1
            slot["amount"] = slot["amount"] + amount
        cust = customers.setdefault(customer, {"orders": 0, "amount": Decimal("0")})
        cust["orders"] = int(cust["orders"]) + 1
        cust["amount"] = cust["amount"] + amount

    ranked = sorted(customers.items(), key=lambda item: (-item[1]["amount"], item[0]))[:10]
    top10 = [
        {
            "customer_id": customer_id,
            "orders": int(stats["orders"]),
            "amount": money(stats["amount"]),
        }
        for customer_id, stats in ranked
    ]
    return {
        "total_orders": len(rows),
        "total_amount": money(total),
        "by_month": _freeze_buckets(by_month, MONTHS),
        "by_status": _freeze_buckets(by_status, STATUSES),
        "by_channel": _freeze_buckets(by_channel, CHANNELS),
        "top10_customers": top10,
    }


def _anomaly(rule: str, row: dict[str, str]) -> dict:
    return {
        "rule": rule,
        "order_id": int(row["order_id"]),
        "customer_id": row["customer_id"],
        "order_date": row["order_date"],
        "amount": money(Decimal(row["amount"])),
        "status": row["status"],
        "channel": row["channel"],
    }


def find_anomalies(rows: list[dict[str, str]]) -> list[dict]:
    """Frozen rules A1–A4. Sorted by order_id, then rule.

    A4 window is the generator domain: 2026-01-01 through 2026-09-30 inclusive.
    """
    counts = Counter(row["order_id"] for row in rows)
    duplicated = {order_id for order_id, count in counts.items() if count > 1}
    anomalies: list[dict] = []
    for row in rows:
        amount = Decimal(row["amount"])
        if amount < Decimal("10.00"):
            anomalies.append(_anomaly("A1", row))
        if row["status"] == "cancelled" and amount > Decimal("1000.00"):
            anomalies.append(_anomaly("A2", row))
        if row["order_id"] in duplicated:
            anomalies.append(_anomaly("A3", row))
        try:
            parsed = date.fromisoformat(row["order_date"])
            out_of_window = parsed < DATE_MIN or parsed > DATE_MAX
        except ValueError:
            out_of_window = True
        if out_of_window:
            anomalies.append(_anomaly("A4", row))
    anomalies.sort(key=lambda item: (item["order_id"], item["rule"]))
    return anomalies


def _examples(anomalies: list[dict], rule: str, limit: int = 3) -> list[dict]:
    return [item for item in anomalies if item["rule"] == rule][:limit]


def build_report(task_id: str, gen: dict, summary: dict, anomalies: list[dict]) -> str:
    counts = Counter(item["rule"] for item in anomalies)
    lines = [
        f"# {task_id} 月度经营报告",
        "",
        "## 概况",
        "",
        f"- task_id: `{task_id}`",
        f"- 订单行数（不含表头）: {summary['total_orders']}",
        f"- total_amount: {summary['total_amount']}",
        "- 金额口径: `total_amount` 与各分组 `amount` 均为 amount 列直接加总，两位小数字符串；不按 paid/refunded/cancelled 轧差。分组计数见 `orders`。",
        f"- orders.csv sha256: `{gen['sha256']}`",
        f"- bytes: {gen['bytes']}（期望 {EXPECTED_BYTES}）",
        f"- lines: {gen['lines']}（期望 {EXPECTED_LINES}，含表头，UTF-8 / LF / 无 BOM）",
        f"- fingerprint_match: {str(gen['match_expected']).lower()}",
        "- 生成: seed=20261108，观察轨 Issue #9 冻结脚本，离线确定性。",
        "- 本报告由产品 Worker 路径写出。生产 7×24 **未验收**；观察轨尚未独立复算。",
        "",
        "## 月度",
        "",
        "| 月份 | 订单数 | 金额 |",
        "|------|--------|------|",
    ]
    for month, bucket in summary["by_month"].items():
        lines.append(f"| {month} | {bucket['orders']} | {bucket['amount']} |")
    lines.extend(["", "## 分布", "", "### 状态", "", "| status | 订单数 | 金额 |", "|--------|--------|------|"])
    for status, bucket in summary["by_status"].items():
        lines.append(f"| {status} | {bucket['orders']} | {bucket['amount']} |")
    lines.extend(["", "### 渠道", "", "| channel | 订单数 | 金额 |", "|---------|--------|------|"])
    for channel, bucket in summary["by_channel"].items():
        lines.append(f"| {channel} | {bucket['orders']} | {bucket['amount']} |")
    lines.extend(["", "## Top10", "", "金额降序，同额按 customer_id 升序。", "", "| 排名 | customer_id | 订单数 | 金额 |", "|------|-------------|--------|------|"])
    for index, item in enumerate(summary["top10_customers"], start=1):
        lines.append(f"| {index} | {item['customer_id']} | {item['orders']} | {item['amount']} |")
    lines.extend(
        [
            "",
            "## 异常",
            "",
            "规则: A1 amount<10.00；A2 status=cancelled 且 amount>1000.00；A3 order_id 重复；A4 日期越界（不在 2026-01-01..2026-09-30，或无法解析）。全集在 `anomalies.json`，按 order_id 升序、同号按规则名升序。示例每类至多 3 条。",
            "",
            "| 规则 | 条数 |",
            "|------|------|",
        ]
    )
    for rule, title in (
        ("A1", "amount<10.00"),
        ("A2", "cancelled 且 amount>1000.00"),
        ("A3", "order_id 重复"),
        ("A4", "日期越界"),
    ):
        lines.append(f"| {rule} {title} | {counts.get(rule, 0)} |")
    for rule in ("A1", "A2", "A3", "A4"):
        lines.extend(["", f"### {rule} 示例", ""])
        sample = _examples(anomalies, rule)
        if not sample:
            lines.append("无")
            continue
        for item in sample:
            lines.append(
                f"- order_id={item['order_id']} customer_id={item['customer_id']} "
                f"order_date={item['order_date']} amount={item['amount']} "
                f"status={item['status']} channel={item['channel']}"
            )
    if not gen["match_expected"]:
        lines.extend(
            [
                "",
                "## BLOCKED",
                "",
                "orders.csv 与冻结指纹不一致。未改规则迁就哈希。本包不得当作 A-1 通过。",
                "",
            ]
        )
    else:
        lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _file_entry(root: Path, path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    return {"path": relpath(root, path), "sha256": sha256_bytes(raw)}


def _update_dispatch(inbox: Path, job_rows: list[dict], *, executed_utc: str, fingerprint_match: bool) -> None:
    path = inbox / "dispatch.json"
    if not path.exists():
        return
    document = json.loads(path.read_text(encoding="utf-8"))
    by_id = {job["job_id"]: job for job in document.get("jobs", [])}
    for row in job_rows:
        current = by_id.get(row["job_id"])
        if current is None:
            document.setdefault("jobs", []).append(row)
            continue
        current.update(row)
    document["executed_utc"] = executed_utc
    document["executed_by"] = "scripts/worker_run_task.py"
    document["fingerprint_match"] = fingerprint_match
    _write_json(path, document)


def run(*, inbox: Path, out: Path, task_id: str) -> dict:
    root = repo_root(inbox)
    data_dir = inbox / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    orders_path = data_dir / "orders.csv"
    raw = render_orders_csv().encode("utf-8")
    orders_path.write_bytes(raw)
    gen = fingerprint(raw)
    executed_utc = utc_now()

    if not gen["match_expected"]:
        blocker = {
            "task_id": task_id,
            "status": "BLOCKED",
            "reason": "fingerprint_mismatch",
            "input": gen,
        }
        report = build_report(
            task_id,
            gen,
            {
                "total_orders": 0,
                "total_amount": "0.00",
                "by_month": {},
                "by_status": {},
                "by_channel": {},
                "top10_customers": [],
            },
            [],
        )
        _write_json(out / "summary.json", blocker)
        _write_json(out / "anomalies.json", [])
        (out / "report.md").write_text(report, encoding="utf-8")
        manifest = {
            "task_id": task_id,
            "generated_at_utc": executed_utc,
            "component_version": COMPONENT_VERSION,
            "input": {"path": relpath(root, orders_path), "sha256": gen["sha256"]},
            "outputs": [
                _file_entry(root, out / "summary.json"),
                _file_entry(root, out / "anomalies.json"),
                _file_entry(root, out / "report.md"),
            ],
            "status": "BLOCKED",
        }
        _write_json(out / "manifest.json", manifest)
        failed = []
        for job_id, title in JOBS:
            failed.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "status": "FAILED",
                    "detail": "BLOCKED fingerprint_mismatch",
                    "evidence": relpath(root, orders_path),
                    "sha256": gen["sha256"],
                }
            )
        _update_dispatch(inbox, failed, executed_utc=executed_utc, fingerprint_match=False)
        return {
            "ok": False,
            "status": "BLOCKED",
            "fingerprint_match": False,
            "sha256_orders": gen["sha256"],
            "bytes": gen["bytes"],
            "lines": gen["lines"],
            "deliverables": relpath(root, out),
        }

    rows = load_rows(orders_path)
    summary = summarize(rows)
    anomalies = find_anomalies(rows)
    summary_path = out / "summary.json"
    anomalies_path = out / "anomalies.json"
    report_path = out / "report.md"
    manifest_path = out / "manifest.json"
    _write_json(summary_path, summary)
    _write_json(anomalies_path, anomalies)
    report_path.write_text(build_report(task_id, gen, summary, anomalies), encoding="utf-8")
    manifest = {
        "task_id": task_id,
        "generated_at_utc": executed_utc,
        "component_version": COMPONENT_VERSION,
        "input": {"path": relpath(root, orders_path), "sha256": gen["sha256"]},
        "outputs": [
            _file_entry(root, summary_path),
            _file_entry(root, anomalies_path),
            _file_entry(root, report_path),
        ],
    }
    _write_json(manifest_path, manifest)
    manifest_meta = _file_entry(root, manifest_path)
    job_evidence = {
        "J1": _file_entry(root, orders_path) | {"bytes": gen["bytes"], "lines": gen["lines"]},
        "J2": _file_entry(root, summary_path),
        "J3": _file_entry(root, anomalies_path),
        "J4": {
            "paths": [
                _file_entry(root, report_path),
                manifest_meta,
            ]
        },
    }
    job_rows = []
    for job_id, title in JOBS:
        evidence = job_evidence[job_id]
        row = {"job_id": job_id, "title": title, "status": "DONE", "evidence": evidence}
        job_rows.append(row)
    _update_dispatch(inbox, job_rows, executed_utc=executed_utc, fingerprint_match=True)
    return {
        "ok": True,
        "status": "DONE",
        "fingerprint_match": True,
        "sha256_orders": gen["sha256"],
        "bytes": gen["bytes"],
        "lines": gen["lines"],
        "total_orders": summary["total_orders"],
        "total_amount": summary["total_amount"],
        "anomaly_count": len(anomalies),
        "deliverables": relpath(root, out),
        "manifest_sha256": manifest_meta["sha256"],
        "output_sha256": {item["path"]: item["sha256"] for item in manifest["outputs"]},
        "component_version": COMPONENT_VERSION,
        "network": False,
    }
