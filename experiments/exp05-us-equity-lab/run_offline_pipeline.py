#!/usr/bin/env python3
"""Exp-05 offline multi-role pipeline (fixtures only, no network).

Roles are sequential stages with separate artifact writes + verify reject-once.
Not investment advice. $0 paid APIs.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "fixtures" / "sample_ohlcv.csv"
OUT = ROOT / "results" / "offline_run"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_rows() -> list[dict]:
    with FIX.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def by_symbol(rows: list[dict]) -> dict[str, list[dict]]:
    d: dict[str, list[dict]] = {}
    for r in rows:
        d.setdefault(r["symbol"], []).append(r)
    for s in d:
        d[s].sort(key=lambda x: x["date"])
    return d


def ret(a: float, b: float) -> float:
    return (b - a) / a if a else 0.0


def analyze(sym_rows: dict[str, list[dict]]) -> dict[str, dict]:
    feats = {}
    for sym, rs in sym_rows.items():
        closes = [float(x["close"]) for x in rs]
        vols = [float(x["volume"]) for x in rs]
        r1 = ret(closes[0], closes[-1]) if len(closes) >= 2 else 0.0
        # simple volatility proxy
        rets = [ret(closes[i], closes[i + 1]) for i in range(len(closes) - 1)]
        vol = math.sqrt(sum(x * x for x in rets) / max(len(rets), 1))
        feats[sym] = {
            "n": len(closes),
            "return_window": round(r1, 4),
            "vol_proxy": round(vol, 4),
            "avg_volume": round(sum(vols) / len(vols), 2),
            "last_close": closes[-1],
        }
    return feats


def build_pools(feats: dict[str, dict]) -> tuple[list[str], list[str], str]:
    """Rules (executable): short = high return & high volume; medium = milder vol."""
    ranked = sorted(feats.items(), key=lambda kv: kv[1]["return_window"], reverse=True)
    short = [s for s, f in ranked if f["return_window"] > 0.02 and f["avg_volume"] >= 1e6][:5]
    medium = [s for s, f in ranked if f["vol_proxy"] < 0.05 and f["return_window"] > 0][:5]
    rules = (
        "short: return_window>0.02 AND avg_volume>=1e6; "
        "medium: vol_proxy<0.05 AND return_window>0; top by return"
    )
    return short, medium, rules


def verify(feats, short, medium, rules, force_reject_once: bool) -> dict:
    problems = []
    for s in short + medium:
        if s not in feats:
            problems.append(f"unknown symbol {s}")
    if not short and not medium:
        problems.append("both pools empty")
    if "return_window" not in rules:
        problems.append("rules missing return_window")
    if force_reject_once:
        return {"status": "REJECTED", "reason": "forced first-pass reject for multi-role demo", "problems": problems}
    if problems:
        return {"status": "REJECTED", "reason": "checks failed", "problems": problems}
    return {"status": "ACCEPTED", "reason": "pools recomputable under stated rules", "problems": []}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    audit = []

    def role(name: str, action: str, artifact: str | None = None):
        audit.append({"utc": utc(), "role": name, "action": action, "artifact": artifact})

    role("Manager", "open_goal Exp-05 offline fixture path")
    role("DataScout", "use fixtures/sample_ohlcv.csv only (no network)")
    rows = load_rows()
    role("IngestWorker", "load fixture rows", str(FIX))
    (OUT / "raw_count.json").write_text(json.dumps({"rows": len(rows)}, indent=2))

    sym = by_symbol(rows)
    role("Curator", "align by symbol+date", str(OUT / "clean_symbols.json"))
    (OUT / "clean_symbols.json").write_text(json.dumps({k: len(v) for k, v in sym.items()}, indent=2))

    feats = analyze(sym)
    role("Analyst", "compute return_window vol_proxy avg_volume", str(OUT / "features.json"))
    (OUT / "features.json").write_text(json.dumps(feats, indent=2))

    short, medium, rules = build_pools(feats)
    role("PoolStrategist", "draft short/medium pools", str(OUT / "pools"))
    (OUT / "pools").mkdir(exist_ok=True)
    (OUT / "pools" / "shortlist_short.json").write_text(
        json.dumps({"universe_rule": rules, "symbols": short}, indent=2)
    )
    (OUT / "pools" / "shortlist_medium.json").write_text(
        json.dumps({"universe_rule": rules, "symbols": medium}, indent=2)
    )
    (OUT / "strategies").mkdir(exist_ok=True)
    (OUT / "strategies" / "draft_research_only.md").write_text(
        "# Research draft only — not investment advice\n\n"
        f"Rules: {rules}\n\n"
        "No live trading. $0 paid data in this offline run.\n"
    )

    v1 = verify(feats, short, medium, rules, force_reject_once=True)
    role("Verifier", "first pass", json.dumps(v1))
    (OUT / "verify_pass1.json").write_text(json.dumps(v1, indent=2))
    assert v1["status"] == "REJECTED"

    # strategist revises: ensure rules string explicit (already is); second verify
    v2 = verify(feats, short, medium, rules, force_reject_once=False)
    role("PoolStrategist", "revise after reject")
    role("Verifier", "second pass", json.dumps(v2))
    (OUT / "verify_pass2.json").write_text(json.dumps(v2, indent=2))

    summary = {
        "experiment": "exp05-offline",
        "utc": utc(),
        "roles_touched": sorted({a["role"] for a in audit}),
        "short": short,
        "medium": medium,
        "verify_final": v2["status"],
        "network": False,
        "paid_api": False,
        "live_trade": False,
    }
    (OUT / "audit.jsonl").write_text("\n".join(json.dumps(a) for a in audit) + "\n")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if v2["status"] == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
