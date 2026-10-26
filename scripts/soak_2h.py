#!/usr/bin/env python3
"""Local soak runner (Windows-friendly).

--direct (default): no OS lock needed.
--via-l1: uses L1 runner with cross-platform lock (fcntl on POSIX, msvcrt on Windows).

Examples:
  py -3 scripts/soak_2h.py --cycles 3 --interval 5
  py -3 scripts/soak_2h.py --cycles 120 --interval 60
  py -3 scripts/soak_2h.py --cycles 120 --interval 60 --via-l1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "progress" / "soak_2h"
OUT.mkdir(parents=True, exist_ok=True)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (r.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def seed_tasks(n: int = 30) -> None:
    sys.path.insert(0, str(ROOT))
    from control_plane.control_plane import ControlPlane
    from control_plane.store import FileStore
    from experiments.exp02_auto_loop.cp_driven_loop import STATE, ensure_goal

    store = FileStore(STATE)
    cp = ControlPlane(store)
    gid = ensure_goal(cp)
    for i in range(n):
        kind = "word_count" if i % 2 == 0 else "checksum"
        payload = {"text": f"soak task {i}"} if kind == "word_count" else {"n": i + 3}
        key = f"soak2h-{i}"
        t = cp.propose_task(
            gid,
            title=f"{kind}:{key}",
            description=json.dumps({"kind": kind, "payload": payload}),
            proposed_by="soak",
            estimated_cost_usd=0.0,
            idempotency_key=key,
            kind=kind,
            payload=payload,
        )
        try:
            cp.approve_task(t.id)
        except Exception:
            pass


def run_once_direct() -> tuple[int, str]:
    """One CP task without L1 lock (always Windows-safe)."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "experiments/exp02_auto_loop/cp_driven_loop.py"), "--once"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT)},
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def run_once_l1() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/l1_runner.py"), "--job", "auto_loop_once"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT)},
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=120)
    ap.add_argument("--interval", type=int, default=60, help="seconds between cycles")
    ap.add_argument("--seed", type=int, default=30)
    ap.add_argument(
        "--via-l1",
        action="store_true",
        help="use L1 runner (cross-platform lock: fcntl POSIX / msvcrt Windows)",
    )
    ap.add_argument("--no-reset-seed", action="store_true")
    args = ap.parse_args()

    log_path = OUT / "soak.log"
    summary_path = OUT / "summary.jsonl"
    sha = git_sha()

    def log(msg: str) -> None:
        line = msg if msg.endswith("\n") else msg + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
        print(msg, flush=True)

    log(f"=== soak start {utc()} sha={sha} cycles={args.cycles} interval={args.interval} via_l1={args.via_l1} ===")

    if not args.no_reset_seed:
        # soft reset of goal seed path used by cp_driven_loop
        try:
            subprocess.run(
                [sys.executable, str(ROOT / "experiments/exp02_auto_loop/cp_driven_loop.py"), "--reset", "--max-steps", "0"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=60,
                env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
            )
        except Exception as e:
            log(f"reset warn: {e}")
        try:
            seed_tasks(args.seed)
            log(f"seeded {args.seed} tasks")
        except Exception as e:
            log(f"seed error: {e}")
            return 1

    runner = run_once_l1 if args.via_l1 else run_once_direct
    ok_n = 0
    for i in range(1, args.cycles + 1):
        ts = utc()
        rc, out = runner()
        if rc == 0:
            ok_n += 1
        log(f"{ts} cycle={i} exit={rc}")
        # trim noisy tails
        tail = out.strip()[-500:] if out else ""
        if tail:
            log(tail)
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"utc": ts, "cycle": i, "exit": rc}) + "\n")
        if i < args.cycles:
            time.sleep(args.interval)

    log(f"=== soak end {utc()} ok={ok_n}/{args.cycles} ===")
    print(f"Log: {log_path}")
    print(f"Summary: {summary_path}")
    return 0 if ok_n == args.cycles else 1


if __name__ == "__main__":
    raise SystemExit(main())
