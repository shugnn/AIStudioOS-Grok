#!/usr/bin/env python3
"""L2-3 style: kill mid-flight then resume without reset (recovery drill).

Not a duration soak — validates restart continuity.

  python scripts/run_recovery_drill.py
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "progress" / "drills"
ENV = {**os.environ, "PYTHONPATH": str(ROOT)}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sha = git_sha()
    receipt: dict = {
        "test": "recovery_drill_kill_resume",
        "git_sha": sha,
        "t0_utc": utc(),
        "steps": [],
        "verdict": "UNKNOWN",
    }

    # Phase 1: start short soak in background
    print("[drill] start short soak...", flush=True)
    soak = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts" / "soak_2h.py"),
            "--cycles",
            "30",
            "--interval",
            "2",
            "--via-l1",
            "--seed",
            "20",
            "--idle-policy",
            "reseed",
            "--metrics-every",
            "5",
        ],
        cwd=str(ROOT),
        env=ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(12)
    if soak.poll() is not None:
        receipt["steps"].append({"phase": "start", "ok": False, "rc": soak.returncode})
        receipt["verdict"] = "FAIL"
        _write(receipt)
        return 1
    receipt["steps"].append({"phase": "start", "ok": True, "pid": soak.pid})

    # Phase 2: kill -9 style
    print(f"[drill] kill soak pid={soak.pid}", flush=True)
    try:
        soak.send_signal(signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        soak.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    receipt["steps"].append({"phase": "kill", "ok": True, "utc": utc()})

    # Phase 3: resume without full reset — one L1 cycle should still work
    print("[drill] resume via L1 auto_loop_once (no --reset)...", flush=True)
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l1_runner.py"), "--job", "auto_loop_once"],
        cwd=str(ROOT),
        env=ENV,
        capture_output=True,
        text=True,
        timeout=120,
    )
    resume_ok = r.returncode == 0
    receipt["steps"].append(
        {
            "phase": "resume_l1",
            "ok": resume_ok,
            "rc": r.returncode,
            "stdout_tail": (r.stdout or "")[-400:],
        }
    )

    # Phase 4: second short soak --no-reset-seed if supported, else brief cycles
    print("[drill] short continue soak...", flush=True)
    r2 = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "soak_2h.py"),
            "--cycles",
            "5",
            "--interval",
            "2",
            "--via-l1",
            "--no-reset-seed",
            "--idle-policy",
            "continue",
            "--metrics-every",
            "5",
        ],
        cwd=str(ROOT),
        env=ENV,
        capture_output=True,
        text=True,
        timeout=180,
    )
    cont_ok = r2.returncode == 0
    receipt["steps"].append(
        {
            "phase": "continue_soak",
            "ok": cont_ok,
            "rc": r2.returncode,
            "stdout_tail": (r2.stdout or "")[-500:],
        }
    )

    receipt["finished_utc"] = utc()
    receipt["verdict"] = "PASS" if resume_ok and cont_ok else "FAIL"
    path = _write(receipt)
    print(json.dumps({"verdict": receipt["verdict"], "path": str(path)}, indent=2), flush=True)
    return 0 if receipt["verdict"] == "PASS" else 1


def _write(receipt: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"recovery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
