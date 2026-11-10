"""Worker jobs for DS-T2-20261110 — invoked only via scripts/worker_run_task.py.

The generator and the summary/anomaly/report口径 are the frozen T1口径
(DS-T1-20261108, commit f2e6347135998004e9542a72b4ca9b368911666c).
Checkpointing and SIGKILL resume live in control_plane.worker_resume.
Do not retune the generator to chase the fingerprint.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

EXPECTED_SHA = "633aded091b1da111f4c3c9c378c975d3bdddf17e85a0fd3b001c7e4ddbf7ffe"
EXPECTED_BYTES = 237705
EXPECTED_LINES = 6001  # header + 6000 data rows, LF, trailing newline
SEED = 20261108
COMPONENT_VERSION = "ds-t2-worker-1"
DATE_MIN = date(2026, 1, 1)
DATE_MAX = date(2026, 9, 30)  # 2026-01-01 + randrange(0, 273) inclusive
MONTHS = tuple(f"2026-{m:02d}" for m in range(1, 10))
STATUSES = ("paid", "pending", "refunded", "cancelled")
CHANNELS = ("web", "app", "store")
CENT = Decimal("0.01")
JOB_SPECS = (
    {"job_id": "J1", "title": "generate_or_verify_orders_csv", "after_boundary": "after_J1_before_J2"},
    {"job_id": "J2", "title": "monthly_summary", "after_boundary": "after_J2_before_J3"},
    {"job_id": "J3", "title": "anomaly_list", "after_boundary": "after_J3_before_J4"},
    {"job_id": "J4", "title": "evidence_pack_manifest", "after_boundary": None},
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT):.2f}"


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dirfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def _dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


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


def _job_generate(inbox: Path) -> dict:
    raw = render_orders_csv().encode("utf-8")
    gen = fingerprint(raw)
    if not gen["match_expected"]:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": "fingerprint_mismatch",
            "extra": {"fingerprint": gen},
        }
    _atomic_bytes(inbox / "data" / "orders.csv", raw)
    return {"ok": True, "artifacts": ["data/orders.csv"], "extra": {"fingerprint": gen}}


def _job_summary(inbox: Path, out: Path) -> dict:
    orders = inbox / "data" / "orders.csv"
    raw = orders.read_bytes()
    gen = fingerprint(raw)
    if not gen["match_expected"]:
        return {"ok": False, "status": "BLOCKED", "reason": "fingerprint_mismatch", "extra": {"fingerprint": gen}}
    summary = summarize(load_rows(orders))
    _atomic_bytes(out / "summary.json", _dumps(summary).encode("utf-8"))
    return {"ok": True, "artifacts": ["deliverables/summary.json"], "extra": {}}


def _job_anomalies(inbox: Path, out: Path) -> dict:
    orders = inbox / "data" / "orders.csv"
    anomalies = find_anomalies(load_rows(orders))
    _atomic_bytes(out / "anomalies.json", _dumps(anomalies).encode("utf-8"))
    return {"ok": True, "artifacts": ["deliverables/anomalies.json"], "extra": {}}


def _job_report(inbox: Path, out: Path, task_id: str, jobs: dict) -> dict:
    orders = inbox / "data" / "orders.csv"
    raw = orders.read_bytes()
    gen = fingerprint(raw)
    recorded = (jobs.get("J1") or {}).get("fingerprint") or {}
    if recorded.get("sha256") != gen["sha256"] or not gen["match_expected"]:
        return {"ok": False, "status": "CORRUPT", "reason": "orders_hash_drift"}
    rows = load_rows(orders)
    fresh_summary = summarize(rows)
    fresh_anomalies = find_anomalies(rows)
    disk_summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    disk_anomalies = json.loads((out / "anomalies.json").read_text(encoding="utf-8"))
    if disk_summary != fresh_summary or disk_anomalies != fresh_anomalies:
        return {"ok": False, "status": "CORRUPT", "reason": "output_drift"}
    text = build_report(task_id, gen, disk_summary, disk_anomalies)
    _atomic_bytes(out / "report.md", text.encode("utf-8"))
    return {"ok": True, "artifacts": ["deliverables/report.md"], "extra": {}}


def execute_job(job_id: str, ctx: dict) -> dict:
    inbox: Path = ctx["inbox"]
    out: Path = ctx["out"]
    if job_id == "J1":
        return _job_generate(inbox)
    if job_id == "J2":
        return _job_summary(inbox, out)
    if job_id == "J3":
        return _job_anomalies(inbox, out)
    if job_id == "J4":
        return _job_report(inbox, out, ctx["task_id"], ctx.get("jobs") or {})
    return {"ok": False, "status": "UNKNOWN_JOB", "reason": job_id}
