#!/usr/bin/env python3
"""L1 Minimal Runner — local, $0 LLM, OS-held exclusive lock (fcntl).

Jobs: heartbeat | dry_protocol_check

Lock model (founder + ChatGPT review):
- Kernel holds the lock on an open fd (fcntl.LOCK_EX).
- While the process is alive and fd is open, the lock is held.
- On process exit / kill -9, the kernel closes fds → lock is released automatically.
- No pid-in-file stale recovery path (avoids non-atomic unlink/recreate races).

Also retains:
- Any required job failure => overall FAILED and non-zero exit code
- max_jobs default 1
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOCK_PATH = ROOT / "docs" / "progress" / ".l1_runner.lock"
OUT_DIR = ROOT / "docs" / "progress"
OUT_DIR.mkdir(parents=True, exist_ok=True)


class OSFileLock:
    """Exclusive lock held by the OS on an open file descriptor.

    Uses fcntl.flock(LOCK_EX | LOCK_NB). The lock lives with the fd/process:
    when the process dies, the kernel drops the lock — no manual zombie reclaim.
    """

    def __init__(self, path: Path):
        self.path = path
        self.fd = None
        self.owner_token = uuid.uuid4().hex

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Open for read/write; create if missing. Do NOT unlink competitors' files.
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        # Optional metadata for humans/debugging only — not used for mutual exclusion
        meta = {
            "pid": os.getpid(),
            "owner_token": self.owner_token,
            "started": time.time(),
            "lock": "fcntl.LOCK_EX",
        }
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
            os.fsync(fd)
        except OSError:
            pass
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None
        # Do not unlink the lock file: other waiters may open the same path;
        # mutual exclusion is the flock, not file existence.


def run_heartbeat(token: str | None) -> dict:
    import subprocess

    if not token:
        return {
            "job": "heartbeat",
            "ok": False,
            "rc": 2,
            "error": "no GH_TOKEN",
        }
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l1_heartbeat.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "job": "heartbeat",
        "ok": r.returncode == 0,
        "rc": r.returncode,
        "stdout_tail": (r.stdout or "")[-500:],
        "stderr_tail": (r.stderr or "")[-300:],
    }


def run_dry_protocol_check() -> dict:
    required = [
        ROOT / "docs" / "05-cross-team-communication-protocol.md",
        ROOT / "docs" / "06-l1-runner-design.md",
        ROOT / "scripts" / "l1_heartbeat.py",
        ROOT / "control_plane" / "control_plane.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    return {
        "job": "dry_protocol_check",
        "ok": len(missing) == 0,
        "rc": 0 if len(missing) == 0 else 1,
        "missing": missing,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--job",
        choices=["heartbeat", "dry_protocol_check", "auto"],
        default="auto",
    )
    ap.add_argument("--simulate-hang", type=int, default=0)
    ap.add_argument("--max-jobs", type=int, default=1)
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    lock = OSFileLock(LOCK_PATH)
    if not lock.acquire():
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "lock_held",
                    "run_id": run_id,
                    "lock": "fcntl",
                }
            )
        )
        return 0

    report = {
        "type": "l1_runner",
        "run_id": run_id,
        "utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "lock": "fcntl.LOCK_EX",
        "owner_token_prefix": lock.owner_token[:8],
        "jobs": [],
        "budget_usd": 0,
        "human_interventions": 0,
    }
    overall_ok = True
    try:
        if args.simulate_hang > 0:
            time.sleep(args.simulate_hang)

        if args.job == "auto":
            jobs = ["dry_protocol_check"][: max(1, args.max_jobs)]
        else:
            jobs = [args.job]

        for j in jobs:
            if j == "heartbeat":
                result = run_heartbeat(token)
            elif j == "dry_protocol_check":
                result = run_dry_protocol_check()
            else:
                result = {"job": j, "ok": False, "rc": 1, "error": "unknown job"}
            report["jobs"].append(result)
            if not result.get("ok", False):
                overall_ok = False

        report["verify"] = {
            "all_jobs_ok": overall_ok,
            "no_llm_spend": True,
            "lock_model": "os_fcntl",
        }
        report["status"] = "ok" if overall_ok else "failed"

        out = OUT_DIR / f"runner-{run_id}.json"
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        tmp.replace(out)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "run_id": run_id,
                    "artifact": str(out),
                    "jobs_ok": overall_ok,
                    "lock": "fcntl",
                },
                indent=2,
            )
        )
        return 0 if overall_ok else 1
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
