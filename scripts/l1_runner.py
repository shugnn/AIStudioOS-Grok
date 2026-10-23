#!/usr/bin/env python3
"""L1 Minimal Runner — local, $0 LLM, atomically file-locked.

Jobs: heartbeat | dry_protocol_check

P0 fixes (ChatGPT review on Grok #5, 2026-10-23):
- Atomic lock via O_CREAT|O_EXCL (no exists-then-write race)
- Never steal lock from a live owner PID; stale only when PID is dead
- Owner token required for release (prevents old process dropping new lock)
- Any required job failure => overall FAILED and non-zero exit code
"""
from __future__ import annotations

import argparse
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


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class FileLock:
    """Exclusive lock using atomic create (O_CREAT|O_EXCL).

    Stale recovery: only if lock file exists AND owner pid is not alive.
    Never preempt a live owner based on TTL alone.
    """

    def __init__(self, path: Path):
        self.path = path
        self.owner_token = uuid.uuid4().hex
        self.fd = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "owner_token": self.owner_token,
            "started": time.time(),
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(self.path), flags, 0o644)
            self.fd = fd
            os.write(fd, json.dumps(payload).encode("utf-8"))
            os.fsync(fd)
            return True
        except FileExistsError:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return False
            pid = int(data.get("pid") or 0)
            if _pid_alive(pid):
                return False
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                return False
            try:
                fd = os.open(str(self.path), flags, 0o644)
                self.fd = fd
                os.write(fd, json.dumps(payload).encode("utf-8"))
                os.fsync(fd)
                return True
            except FileExistsError:
                return False

    def release(self) -> None:
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("owner_token") != self.owner_token:
                return
            if data.get("pid") != os.getpid():
                return
            if self.fd is not None:
                try:
                    os.close(self.fd)
                except OSError:
                    pass
                self.fd = None
            self.path.unlink(missing_ok=True)
        except Exception:
            pass


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
    lock = FileLock(LOCK_PATH)
    if not lock.acquire():
        print(
            json.dumps(
                {"status": "skipped", "reason": "lock_held", "run_id": run_id}
            )
        )
        return 0

    report = {
        "type": "l1_runner",
        "run_id": run_id,
        "utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
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
                },
                indent=2,
            )
        )
        return 0 if overall_ok else 1
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
