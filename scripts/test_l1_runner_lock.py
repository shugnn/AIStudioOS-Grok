#!/usr/bin/env python3
"""Automated regression tests for L1 runner lock + exit codes.

Run: python scripts/test_l1_runner_lock.py
Exit 0 only if all assertions pass.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = [sys.executable, str(ROOT / "scripts" / "l1_runner.py")]


def run(args, env=None, timeout=60):
    e = os.environ.copy()
    if env is not None:
        e.update(env)
    return subprocess.run(
        RUNNER + args,
        cwd=str(ROOT),
        env=e,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main() -> int:
    failures = []

    # T1: concurrent — second must be skipped (exit 2)
    p1 = subprocess.Popen(
        RUNNER + ["--job", "dry_protocol_check", "--simulate-hang", "3"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.5)
    r2 = run(["--job", "dry_protocol_check"])
    p1.wait(timeout=30)
    if r2.returncode != 2 or "lock_held" not in (r2.stdout or ""):
        failures.append(f"T1 concurrent expected exit 2 lock_held, got rc={r2.returncode} out={r2.stdout!r}")
    else:
        print("PASS T1 concurrent lock_held exit 2")

    # T2: kill -9 recovery
    p = subprocess.Popen(
        RUNNER + ["--job", "dry_protocol_check", "--simulate-hang", "30"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.5)
    p.kill()
    try:
        p.wait(timeout=5)
    except Exception:
        pass
    time.sleep(0.3)
    r = run(["--job", "dry_protocol_check"])
    if r.returncode != 0 or '"status": "ok"' not in (r.stdout or "") and '"status":"ok"' not in (r.stdout or ""):
        # accept status ok in json
        if r.returncode != 0:
            failures.append(f"T2 recovery expected rc 0, got {r.returncode} {r.stdout!r}")
        else:
            print("PASS T2 kill -9 recovery")
    else:
        print("PASS T2 kill -9 recovery")

    # T3: failure propagation exit 1
    env = os.environ.copy()
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    r = subprocess.run(
        RUNNER + ["--job", "heartbeat"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 1:
        failures.append(f"T3 expected exit 1, got {r.returncode} {r.stdout!r}")
    else:
        print("PASS T3 heartbeat no token exit 1")

    # T4: normal success exit 0
    r = run(["--job", "dry_protocol_check"])
    if r.returncode != 0:
        failures.append(f"T4 expected exit 0, got {r.returncode}")
    else:
        print("PASS T4 normal ok")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
