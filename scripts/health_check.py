#!/usr/bin/env python3
"""One-shot local health check for AIStudioOS-Grok ($0, no long soak).

Checks: imports, emergency stop module, L1 dry job, CP --once after reset seed=1.
Exit 0 only if all steps ok (and not emergency-stopped).

  py -3 scripts/health_check.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def step(name: str, ok: bool, detail: str = "") -> dict:
    row = {"step": name, "ok": ok, "detail": detail}
    print(json.dumps(row, ensure_ascii=False))
    return row


def main() -> int:
    results: list[dict] = []

    try:
        from control_plane.emergency_stop import is_stopped, STOP_PATH

        if is_stopped():
            results.append(step("emergency_stop", False, f"armed at {STOP_PATH}"))
            print(json.dumps({"overall_ok": False, "results": results}, indent=2))
            return 3
        results.append(step("emergency_stop", True, "not armed"))
    except Exception as e:
        results.append(step("emergency_stop", False, str(e)))

    try:
        from control_plane.control_plane import ControlPlane
        from control_plane.store import FileStore

        results.append(step("import_control_plane", True))
    except Exception as e:
        results.append(step("import_control_plane", False, str(e)))

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l1_runner.py"), "--job", "dry_protocol_check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)},
    )
    results.append(
        step(
            "l1_dry_protocol",
            r.returncode == 0,
            (r.stdout or r.stderr or "")[-200:],
        )
    )

    env = {**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)}
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "experiments" / "exp02_auto_loop" / "cp_driven_loop.py"),
            "--reset",
            "--max-steps",
            "0",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    # seed one task via soak helper logic inline
    try:
        from control_plane.control_plane import ControlPlane
        from control_plane.store import FileStore
        from experiments.exp02_auto_loop.cp_driven_loop import STATE, ensure_goal
        import json as _json
        import time

        store = FileStore(STATE)
        cp = ControlPlane(store)
        gid = ensure_goal(cp)
        key = f"health-{int(time.time())}"
        t = cp.propose_task(
            gid,
            title=f"checksum:{key}",
            description=_json.dumps({"kind": "checksum", "payload": {"n": 7}}),
            proposed_by="health_check",
            estimated_cost_usd=0.0,
            idempotency_key=key,
            kind="checksum",
            payload={"n": 7},
        )
        cp.approve_task(t.id)
        results.append(step("seed_one", True, t.id))
    except Exception as e:
        results.append(step("seed_one", False, str(e)))

    r2 = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "l1_runner.py"),
            "--job",
            "auto_loop_once",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    results.append(
        step(
            "l1_auto_loop_once",
            r2.returncode == 0,
            (r2.stdout or "")[-300:],
        )
    )

    overall = all(x["ok"] for x in results)
    print(json.dumps({"overall_ok": overall, "results": results}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
