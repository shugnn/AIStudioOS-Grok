#!/usr/bin/env python3
"""Exp-05 live ingest — free public quotes via yfinance only.

FOUNDER-approved network for free sources. No paid API keys. No live trading.

  pip install -r experiments/exp05-us-equity-lab/requirements-exp05.txt
  python experiments/exp05-us-equity-lab/ingest_live_free.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "datalake" / "raw"
META = ROOT / "datalake" / "meta"

# Liquid US names for engineering pressure test (not a recommendation list)
DEFAULT_SYMBOLS = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "JPM",
    "XOM",
]


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    try:
        import yfinance as yf
    except ImportError:
        print(
            "Missing yfinance. Run:\n  pip install -r experiments/exp05-us-equity-lab/requirements-exp05.txt",
            file=sys.stderr,
        )
        return 2

    RAW.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)
    symbols = DEFAULT_SYMBOLS
    period = "6mo"
    interval = "1d"

    report = {
        "utc": utc(),
        "source": "yfinance",
        "paid_api": False,
        "live_trade": False,
        "period": period,
        "interval": interval,
        "symbols": symbols,
        "files": [],
        "errors": [],
    }

    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            df = t.history(period=period, interval=interval, auto_adjust=True)
            if df is None or df.empty:
                report["errors"].append({"symbol": sym, "error": "empty"})
                continue
            df = df.reset_index()
            # normalize columns
            colmap = {c: c.title() for c in df.columns}
            df = df.rename(columns=colmap)
            if "Date" in df.columns:
                df["Date"] = df["Date"].astype(str).str[:10]
            out = RAW / f"{sym}_{period}_{interval}.csv"
            cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            df[cols].to_csv(out, index=False)
            report["files"].append(
                {"symbol": sym, "path": str(out.relative_to(ROOT)), "rows": len(df)}
            )
            print(f"OK {sym} rows={len(df)} -> {out.name}", flush=True)
        except Exception as e:
            report["errors"].append({"symbol": sym, "error": str(e)})
            print(f"FAIL {sym}: {e}", flush=True)

    meta_path = META / f"ingest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    meta_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": len(report["files"]) > 0, "meta": str(meta_path), "n_ok": len(report["files"]), "n_err": len(report["errors"])}, indent=2))
    return 0 if report["files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
