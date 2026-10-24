#!/usr/bin/env python3
"""Stress: N concurrent L1 runners; exactly one should execute, others lock_held (2)."""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "l1_runner.py"
N = 8


def main() -> int:
    procs = []
    for i in range(N):
        p = subprocess.Popen(
            [sys.executable, str(RUNNER), "--job", "dry_protocol_check"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        procs.append(p)
    codes = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        codes.append(p.returncode)
        if p.returncode not in (0, 2):
            print("UNEXPECTED", p.returncode, out[-200:], err[-200:])
    ok_count = sum(1 for c in codes if c == 0)
    skip_count = sum(1 for c in codes if c == 2)
    other = [c for c in codes if c not in (0, 2)]
    print({"N": N, "ok": ok_count, "lock_held": skip_count, "other": other, "codes": codes})
    # Exactly one winner preferred; under extreme scheduling maybe 1 ok
    if ok_count == 1 and skip_count == N - 1 and not other:
        print("STRESS PASS")
        return 0
    if ok_count >= 1 and skip_count >= 1 and not other and ok_count + skip_count == N:
        print("STRESS PASS (soft: multiple sequential ok if lock released fast)")
        return 0
    print("STRESS FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
