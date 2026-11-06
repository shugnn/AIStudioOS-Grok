#!/usr/bin/env python3
"""Emergency-stop drill: arm EMERGENCY_STOP, expect L1 exit 3, then clear.

  python scripts/run_emergency_stop_drill.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOP = ROOT / "docs" / "progress" / "EMERGENCY_STOP"
OUT = ROOT / "docs" / "progress" / "drills"
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if STOP.exists():
        STOP.unlink()

    receipt = {"test": "emergency_stop_drill", "t0_utc": utc(), "steps": []}

    # baseline: should work
    r0 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l1_runner.py"), "--job", "dry_protocol_check"],
        cwd=str(ROOT),
        env=ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    receipt["steps"].append({"phase": "baseline_dry", "rc": r0.returncode, "ok": r0.returncode == 0})

    STOP.write_text("drill\n", encoding="utf-8")
    r1 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l1_runner.py"), "--job", "auto_loop_once"],
        cwd=str(ROOT),
        env=ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    armed_ok = r1.returncode == 3
    receipt["steps"].append(
        {
            "phase": "armed_expect_exit_3",
            "rc": r1.returncode,
            "ok": armed_ok,
            "stdout_tail": (r1.stdout or "")[-300:],
        }
    )

    STOP.unlink(missing_ok=True)
    r2 = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l1_runner.py"), "--job", "dry_protocol_check"],
        cwd=str(ROOT),
        env=ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    cleared_ok = r2.returncode == 0
    receipt["steps"].append({"phase": "cleared", "rc": r2.returncode, "ok": cleared_ok})

    receipt["finished_utc"] = utc()
    receipt["verdict"] = (
        "PASS" if receipt["steps"][0]["ok"] and armed_ok and cleared_ok else "FAIL"
    )
    path = OUT / f"emergency-stop-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": receipt["verdict"], "path": str(path)}, indent=2))
    return 0 if receipt["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
