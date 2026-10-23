#!/usr/bin/env python3
"""L1 Minimal Runner — local, $0 LLM, file-locked.

Jobs: heartbeat | dry_protocol_check
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


class FileLock:
    def __init__(self, path: Path, ttl_sec: int = 600):
        self.path = path
        self.ttl_sec = ttl_sec
        self.fd = None

    def acquire(self) -> bool:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                pid = data.get("pid")
                started = data.get("started", 0)
                alive = False
                if pid:
                    try:
                        os.kill(pid, 0)
                        alive = True
                    except OSError:
                        alive = False
                if alive and (time.time() - started) < self.ttl_sec:
                    return False
            except Exception:
                pass
        payload = {"pid": os.getpid(), "started": time.time(), "run_id": None}
        self.path.write_text(json.dumps(payload))
        return True

    def release(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if data.get("pid") == os.getpid():
                    self.path.unlink(missing_ok=True)
        except Exception:
            pass


def run_heartbeat(token: str | None) -> dict:
    # Reuse heartbeat module logic via subprocess for isolation
    import subprocess
    env = os.environ.copy()
    if token:
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
        "missing": missing,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", choices=["heartbeat", "dry_protocol_check", "auto"], default="auto")
    ap.add_argument("--simulate-hang", type=int, default=0, help="sleep N sec after lock (for kill test)")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    lock = FileLock(LOCK_PATH)
    if not lock.acquire():
        print(json.dumps({"status": "skipped", "reason": "lock_held", "run_id": run_id}))
        return 0

    report = {
        "type": "l1_runner",
        "run_id": run_id,
        "utc": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "jobs": [],
        "budget_usd": 0,
        "human_interventions": 0,
    }
    try:
        if args.simulate_hang > 0:
            time.sleep(args.simulate_hang)

        jobs = []
        if args.job == "auto":
            jobs = ["dry_protocol_check", "heartbeat"]
        else:
            jobs = [args.job]

        for j in jobs:
            if j == "heartbeat":
                if not token:
                    report["jobs"].append({"job": "heartbeat", "ok": False, "error": "no GH_TOKEN"})
                else:
                    report["jobs"].append(run_heartbeat(token))
            elif j == "dry_protocol_check":
                report["jobs"].append(run_dry_protocol_check())

        # verify
        report["verify"] = {
            "all_protocol_ok": all(
                x.get("ok", x.get("rc") == 0) for x in report["jobs"] if x.get("job") == "dry_protocol_check"
            ) or not any(x.get("job") == "dry_protocol_check" for x in report["jobs"]),
            "no_llm_spend": True,
        }
        out = OUT_DIR / f"runner-{run_id}.json"
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2))
        tmp.replace(out)
        print(json.dumps({"status": "ok", "run_id": run_id, "artifact": str(out)}, indent=2))
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
