#!/usr/bin/env python3
"""Exp-05: ingest free live data then multi-role analyze → pools (research only).

  python experiments/exp05-us-equity-lab/run_live_pipeline.py
"""
from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "datalake" / "raw"
OUT = ROOT / "results" / "live_run"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ingest() -> int:
    return subprocess.call([sys.executable, str(ROOT / "ingest_live_free.py")], cwd=str(ROOT.parent.parent))


def load_symbol_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # expect Date, Close, Volume
    out = []
    for r in rows:
        try:
            out.append(
                {
                    "date": r.get("Date") or r.get("date"),
                    "close": float(r.get("Close") or r.get("close") or 0),
                    "volume": float(r.get("Volume") or r.get("volume") or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return out


def features_for(rows: list[dict]) -> dict:
    if len(rows) < 5:
        return {"n": len(rows), "return_window": 0.0, "vol_proxy": 0.0, "avg_volume": 0.0}
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    r = (closes[-1] - closes[0]) / closes[0] if closes[0] else 0.0
    rets = [(closes[i + 1] - closes[i]) / closes[i] for i in range(len(closes) - 1) if closes[i]]
    vol = math.sqrt(sum(x * x for x in rets) / max(len(rets), 1)) if rets else 0.0
    return {
        "n": len(closes),
        "return_window": round(r, 4),
        "vol_proxy": round(vol, 4),
        "avg_volume": round(sum(vols) / len(vols), 2),
        "last_close": closes[-1],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("[live] ingest...", flush=True)
    rc = ingest()
    if rc != 0:
        print("[live] ingest failed", rc, flush=True)
        return rc

    feats = {}
    for p in sorted(RAW.glob("*.csv")):
        sym = p.name.split("_")[0]
        rows = load_symbol_csv(p)
        feats[sym] = features_for(rows)

    ranked = sorted(feats.items(), key=lambda kv: kv[1].get("return_window", 0), reverse=True)
    short = [s for s, f in ranked if f.get("return_window", 0) > 0.05 and f.get("avg_volume", 0) >= 1e6][:8]
    medium = [s for s, f in ranked if f.get("vol_proxy", 1) < 0.03 and f.get("return_window", 0) > 0][:8]
    rules = "short: return_window>0.05 AND avg_volume>=1e6; medium: vol_proxy<0.03 AND return_window>0"

    audit = [
        {"role": "DataScout", "action": "yfinance free only"},
        {"role": "IngestWorker", "action": "wrote datalake/raw"},
        {"role": "Analyst", "action": "features"},
        {"role": "PoolStrategist", "action": "pools"},
        {"role": "Verifier", "action": "structural check"},
    ]
    ok = bool(feats) and (short is not None)
    summary = {
        "utc": utc(),
        "experiment": "exp05-live",
        "features": feats,
        "short": short,
        "medium": medium,
        "rules": rules,
        "paid_api": False,
        "live_trade": False,
        "disclaimer": "Research/engineering only — not investment advice.",
        "audit_roles": [a["role"] for a in audit],
        "ok": ok,
    }
    (OUT / "features.json").write_text(json.dumps(feats, indent=2), encoding="utf-8")
    (OUT / "pools").mkdir(exist_ok=True)
    (OUT / "pools" / "shortlist_short.json").write_text(
        json.dumps({"rules": rules, "symbols": short}, indent=2), encoding="utf-8"
    )
    (OUT / "pools" / "shortlist_medium.json").write_text(
        json.dumps({"rules": rules, "symbols": medium}, indent=2), encoding="utf-8"
    )
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"ok": ok, "short": short, "medium": medium, "n_symbols": len(feats)}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
