"""Worker jobs for DS-T1-20261108 — invoked only via scripts/worker_run_task.py.

Data generation must match frozen fingerprint when generator spec is complete.
If DS published a canonical generator, replace generate_orders() with that exact algorithm.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

EXPECTED_SHA = "633aded091b1da111f4c3c9c378c975d3bdddf17e85a0fd3b001c7e4ddbf7ffe"
EXPECTED_BYTES = 237705
EXPECTED_LINES = 6001  # header + 6000
SEED = 20261108
N = 6000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_orders(path: Path) -> dict:
    """Deterministic placeholder schema until DS locks column layout.

    If fingerprint mismatches, status=fingerprint_mismatch and DS must supply
    canonical generator — we do not invent a matching hash by trial-and-error spam.
    """
    rng = random.Random(SEED)
    start = date(2024, 1, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["order_id", "order_date", "amount", "status", "customer_id", "region"])
        for i in range(1, N + 1):
            d = start + timedelta(days=(i * 7 + rng.randint(0, 3)) % 365)
            amount = round(rng.uniform(5.0, 2000.0), 2)
            status = ["paid", "pending", "cancelled", "refunded"][rng.randint(0, 3)]
            # inject anomalies: negative-like huge refund flags via status+amount
            if i % 997 == 0:
                amount = round(amount + 50000, 2)
                status = "paid"
            if i % 991 == 0:
                status = "cancelled"
                amount = 0.0
            w.writerow([f"ORD{i:05d}", d.isoformat(), f"{amount:.2f}", status, f"C{rng.randint(1, 800)}", rng.choice(["CN", "US", "EU", "JP"])])
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    lines = raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)
    return {
        "path": str(path),
        "sha256": digest,
        "bytes": len(raw),
        "lines": lines,
        "match_expected": digest == EXPECTED_SHA and len(raw) == EXPECTED_BYTES,
        "expected_sha256": EXPECTED_SHA,
    }


def analyze(path: Path) -> tuple[dict, list]:
    by_month: dict[str, dict] = defaultdict(lambda: {"orders": 0, "amount_sum": 0.0, "by_status": defaultdict(int)})
    anomalies = []
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            od = row["order_date"]
            month = od[:7]
            amt = float(row["amount"])
            st = row["status"]
            by_month[month]["orders"] += 1
            by_month[month]["amount_sum"] += amt
            by_month[month]["by_status"][st] += 1
            if amt > 10000:
                anomalies.append({"type": "amount_outlier", "order_id": row["order_id"], "amount": amt})
            if st == "cancelled" and amt > 0:
                anomalies.append({"type": "cancelled_with_amount", "order_id": row["order_id"], "amount": amt})
            if st == "refunded" and amt <= 0:
                anomalies.append({"type": "refund_nonpositive", "order_id": row["order_id"], "amount": amt})
    summary = {
        "task_id": "DS-T1-20261108",
        "months": {
            m: {
                "orders": v["orders"],
                "amount_sum": round(v["amount_sum"], 2),
                "by_status": dict(v["by_status"]),
            }
            for m, v in sorted(by_month.items())
        },
        "anomaly_count": len(anomalies),
    }
    return summary, anomalies


def run(*, inbox: Path, out: Path, task_id: str) -> dict:
    data_dir = inbox / "data"
    orders = data_dir / "orders.csv"
    gen = generate_orders(orders)
    summary, anomalies = analyze(orders)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "anomalies.json").write_text(json.dumps(anomalies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = [
        f"# Report {task_id}",
        "",
        f"- orders sha256: `{gen['sha256']}`",
        f"- bytes: {gen['bytes']} lines: {gen['lines']}",
        f"- fingerprint_match: {gen['match_expected']}",
        f"- anomaly_count: {len(anomalies)}",
        "",
        "## Monthly summary",
        "",
        "```json",
        json.dumps(summary["months"], indent=2, ensure_ascii=False),
        "```",
        "",
        "## Note",
        "",
        "If fingerprint_match is false, canonical generator from DS freeze is required;",
        "this Worker path still produced summary/anomalies from its deterministic series.",
        "",
    ]
    (out / "report.md").write_text("\n".join(report), encoding="utf-8")

    def file_meta(p: Path) -> dict:
        b = p.read_bytes()
        return {"path": str(p.relative_to(inbox.parent.parent) if False else p.name), "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}

    # paths relative to repo root style
    def meta(p: Path) -> dict:
        b = p.read_bytes()
        return {
            "path": str(p.relative_to(inbox.parent.parent)) if inbox.parent.name == "task_inbox" else str(p),
            "sha256": hashlib.sha256(b).hexdigest(),
            "bytes": len(b),
        }

    # fix relative: inbox is task_inbox/DS-...
    root = inbox.parent.parent

    def meta_root(p: Path) -> dict:
        b = p.read_bytes()
        return {"path": str(p.relative_to(root)).replace("\\", "/"), "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}

    manifest = {
        "task_id": task_id,
        "input": {
            "orders.csv": {
                "sha256": gen["sha256"],
                "bytes": gen["bytes"],
                "lines": gen["lines"],
                "expected_sha256": EXPECTED_SHA,
                "match": gen["match_expected"],
            }
        },
        "outputs": {
            "summary.json": meta_root(out / "summary.json"),
            "anomalies.json": meta_root(out / "anomalies.json"),
            "report.md": meta_root(out / "report.md"),
        },
        "generator_seed": SEED,
        "network": False,
        "worker": "task_inbox/DS-T1-20261108/worker_jobs.py via scripts/worker_run_task.py",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["outputs"]["manifest.json"] = meta_root(out / "manifest.json")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "fingerprint_match": gen["match_expected"],
        "deliverables": str(out),
        "sha256_orders": gen["sha256"],
    }
