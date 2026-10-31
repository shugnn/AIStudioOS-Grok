#!/usr/bin/env python3
"""L1 Minimal Runner — local, $0 LLM, OS-held exclusive lock (cross-platform).

PLATFORM:
- POSIX (Linux/macOS): fcntl.flock(LOCK_EX | LOCK_NB)
- Windows: msvcrt.locking on a fixed region of the lock file

Exit codes:
- 0 ok
- 1 failed job
- 2 skipped (lock_held)
- 3 emergency stop (docs/progress/EMERGENCY_STOP present)
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
from control_plane.emergency_stop import is_stopped, reason, status as stop_status

LOCK_PATH = ROOT / "docs" / "progress" / ".l1_runner.lock"
OUT_DIR = ROOT / "docs" / "progress"
OUT_DIR.mkdir(parents=True, exist_ok=True)

IS_WINDOWS = sys.platform.startswith("win")
if IS_WINDOWS:
    import msvcrt

    LOCK_BACKEND = "msvcrt"
else:
    import fcntl

    LOCK_BACKEND = "fcntl"

_LOCK_REGION = 1


class OSFileLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd = None
        self.owner_token = uuid.uuid4().hex
        self.backend = LOCK_BACKEND

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if IS_WINDOWS:
                try:
                    size = os.fstat(fd).st_size
                    if size < _LOCK_REGION:
                        os.write(fd, b"\0" * (_LOCK_REGION - size))
                        os.lseek(fd, 0, os.SEEK_SET)
                except OSError:
                    pass
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, _LOCK_REGION)
                except OSError:
                    os.close(fd)
                    return False
            else:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(fd)
                    return False
                except OSError as e:
                    os.close(fd)
                    print(json.dumps({"error": "flock_failed", "detail": str(e)}), file=sys.stderr)
                    raise
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        meta = {
            "pid": os.getpid(),
            "owner_token": self.owner_token,
            "started": time.time(),
            "lock": f"{self.backend}.LOCK_EX",
            "platform": sys.platform,
        }
        try:
            if IS_WINDOWS:
                os.lseek(fd, _LOCK_REGION, os.SEEK_SET)
                os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
            else:
                os.ftruncate(fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
            os.fsync(fd)
        except OSError as e:
            print(json.dumps({"warning": "lock_metadata_write_failed", "error": str(e)}), file=sys.stderr)
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            if IS_WINDOWS:
                try:
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, _LOCK_REGION)
                except OSError:
                    pass
            else:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


def run_heartbeat(token: str | None) -> dict:
    import subprocess

    if not token:
        return {"job": "heartbeat", "ok": False, "rc": 2, "error": "no GH_TOKEN"}
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


def run_auto_loop_once() -> dict:
    import subprocess

    script = ROOT / "experiments" / "exp02_auto_loop" / "cp_driven_loop.py"
    r = subprocess.run(
        [sys.executable, str(script), "--once"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "job": "auto_loop_once",
        "ok": r.returncode == 0,
        "rc": r.returncode,
        "stdout_tail": (r.stdout or "")[-800:],
        "stderr_tail": (r.stderr or "")[-300:],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--job",
        choices=["heartbeat", "dry_protocol_check", "auto_loop_once", "auto"],
        default="auto",
    )
    ap.add_argument("--simulate-hang", type=int, default=0)
    ap.add_argument("--max-jobs", type=int, default=1)
    args = ap.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]

    if is_stopped():
        print(
            json.dumps(
                {
                    "status": "emergency_stop",
                    "run_id": run_id,
                    "reason": reason() or "EMERGENCY_STOP file present",
                    **stop_status(),
                }
            )
        )
        return 3

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    lock = OSFileLock(LOCK_PATH)
    if not lock.acquire():
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "lock_held",
                    "run_id": run_id,
                    "lock": lock.backend,
                    "platform": sys.platform,
                }
            )
        )
        return 2

    report = {
        "type": "l1_runner",
        "run_id": run_id,
        "utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "lock": f"{lock.backend}.LOCK_EX",
        "lock_backend": lock.backend,
        "platform": sys.platform,
        "owner_token_prefix": lock.owner_token[:8],
        "jobs": [],
        "budget_usd": 0,
        "human_interventions": 0,
    }
    overall_ok = True
    try:
        if args.simulate_hang > 0:
            time.sleep(args.simulate_hang)

        if is_stopped():
            report["status"] = "emergency_stop"
            report["verify"] = {"all_jobs_ok": False, "emergency_stop": True}
            out = OUT_DIR / f"runner-{run_id}.json"
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"status": "emergency_stop", "run_id": run_id, **stop_status()}, indent=2))
            return 3

        if args.job == "auto":
            jobs = ["dry_protocol_check"][: max(1, args.max_jobs)]
        else:
            jobs = [args.job]

        for j in jobs:
            if j == "heartbeat":
                result = run_heartbeat(token)
            elif j == "dry_protocol_check":
                result = run_dry_protocol_check()
            elif j == "auto_loop_once":
                result = run_auto_loop_once()
            else:
                result = {"job": j, "ok": False, "rc": 1, "error": "unknown job"}
            report["jobs"].append(result)
            if not result.get("ok", False):
                overall_ok = False

        report["verify"] = {
            "all_jobs_ok": overall_ok,
            "no_llm_spend": True,
            "lock_model": f"os_{lock.backend}",
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
                    "lock": lock.backend,
                    "platform": sys.platform,
                },
                indent=2,
            )
        )
        return 0 if overall_ok else 1
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
