#!/usr/bin/env python3
"""Local soak runner (Windows-friendly).

--direct (default): no OS lock needed.
--via-l1: uses L1 runner with cross-platform lock (fcntl on POSIX, msvcrt on Windows).

Metrics (FOUNDER 2026-10-28):
  Never treat exit=0 alone as business success.
  Reports cycles_total, cycles_exit0, cycles_with_work, cycles_idle, tasks_done_unique.
  idle_policy: continue | stop | reseed

Examples:
  py -3 scripts/soak_2h.py --cycles 3 --interval 5
  py -3 scripts/soak_2h.py --cycles 120 --interval 60 --via-l1 --idle-policy stop
  py -3 scripts/soak_2h.py --cycles 120 --interval 60 --via-l1 --seed 120 --idle-policy reseed
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "progress" / "soak_2h"
OUT.mkdir(parents=True, exist_ok=True)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_sha(short: bool = False) -> str:
    try:
        args = ["git", "rev-parse"]
        if short:
            args.append("--short")
        args.append("HEAD")
        r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def seed_tasks(n: int = 30, prefix: str = "soak2h") -> int:
    sys.path.insert(0, str(ROOT))
    from control_plane.control_plane import ControlPlane
    from control_plane.store import FileStore
    from experiments.exp02_auto_loop.cp_driven_loop import STATE, ensure_goal

    store = FileStore(STATE)
    cp = ControlPlane(store)
    gid = ensure_goal(cp)
    created = 0
    for i in range(n):
        kind = "word_count" if i % 2 == 0 else "checksum"
        payload = {"text": f"soak task {i}"} if kind == "word_count" else {"n": i + 3}
        key = f"{prefix}-{i}-{int(time.time())}" if prefix != "soak2h" else f"{prefix}-{i}"
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
            created += 1
        except Exception:
            pass
    return created


def run_once_direct() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(ROOT / "experiments/exp02_auto_loop/cp_driven_loop.py"), "--once"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)},
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
        env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)},
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    objs: list[dict[str, Any]] = []
    if not text:
        return objs
    # Prefer whole-line JSON
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                o = json.loads(s)
                if isinstance(o, dict):
                    objs.append(o)
            except json.JSONDecodeError:
                pass
    # Fallback: nested blobs in stdout_tail strings
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
        try:
            o = json.loads(m.group(0))
            if isinstance(o, dict):
                objs.append(o)
        except json.JSONDecodeError:
            continue
    return objs


def classify_cycle(rc: int, out: str) -> dict[str, Any]:
    """Classify one cycle: exit ok vs business work.

    with_work if steps_this_wake > 0, or accepted increased, or jobs show progress.
    """
    steps = 0
    accepted = None
    found_cp = False
    for o in _extract_json_objects(out):
        if "steps_this_wake" in o:
            found_cp = True
            try:
                steps = int(o.get("steps_this_wake") or 0)
            except (TypeError, ValueError):
                steps = 0
            if "accepted" in o:
                try:
                    accepted = int(o.get("accepted") or 0)
                except (TypeError, ValueError):
                    accepted = None
            break
        # L1 wrapper may embed CP JSON in stdout_tail
        tail = o.get("stdout_tail") or o.get("jobs", [{}])[0].get("stdout_tail") if o.get("jobs") else None
        if isinstance(tail, str) and "steps_this_wake" in tail:
            for inner in _extract_json_objects(tail):
                if "steps_this_wake" in inner:
                    found_cp = True
                    try:
                        steps = int(inner.get("steps_this_wake") or 0)
                    except (TypeError, ValueError):
                        steps = 0
                    if "accepted" in inner:
                        try:
                            accepted = int(inner.get("accepted") or 0)
                        except (TypeError, ValueError):
                            accepted = None
                    break

    with_work = steps > 0
    idle = (rc == 0) and (not with_work)
    return {
        "exit": rc,
        "steps_this_wake": steps,
        "accepted_cum": accepted,
        "with_work": with_work,
        "idle": idle,
        "cp_parsed": found_cp,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=120)
    ap.add_argument("--interval", type=int, default=60, help="seconds between cycles")
    ap.add_argument("--seed", type=int, default=None, help="tasks to seed (default=max(cycles, 30))")
    ap.add_argument(
        "--via-l1",
        action="store_true",
        help="use L1 runner (cross-platform lock: fcntl POSIX / msvcrt Windows)",
    )
    ap.add_argument("--no-reset-seed", action="store_true")
    ap.add_argument(
        "--idle-policy",
        choices=["continue", "stop", "reseed"],
        default="stop",
        help="continue=old behavior; stop=end after consecutive idles; reseed=add more tasks",
    )
    ap.add_argument(
        "--idle-stop-after",
        type=int,
        default=3,
        help="consecutive idle cycles before stop/reseed action",
    )
    ap.add_argument("--reseed-batch", type=int, default=30)
    args = ap.parse_args()

    seed_n = args.seed if args.seed is not None else max(args.cycles, 30)

    log_path = OUT / "soak.log"
    summary_path = OUT / "summary.jsonl"
    metrics_path = OUT / "metrics.json"
    sha_short = git_sha(short=True)
    sha_full = git_sha(short=False)

    def log(msg: str) -> None:
        line = msg if msg.endswith("\n") else msg + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
        print(msg, flush=True)

    log(
        f"=== soak start {utc()} sha={sha_short} sha_full={sha_full} "
        f"cycles={args.cycles} interval={args.interval} via_l1={args.via_l1} "
        f"seed={seed_n} idle_policy={args.idle_policy} ==="
    )

    if not args.no_reset_seed:
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "experiments/exp02_auto_loop/cp_driven_loop.py"),
                    "--reset",
                    "--max-steps",
                    "0",
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=60,
                env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
            )
        except Exception as e:
            log(f"reset warn: {e}")
        try:
            n = seed_tasks(seed_n)
            log(f"seeded {n}/{seed_n} tasks")
        except Exception as e:
            log(f"seed error: {e}")
            return 1

    runner = run_once_l1 if args.via_l1 else run_once_direct
    cycles_exit0 = 0
    cycles_with_work = 0
    cycles_idle = 0
    consecutive_idle = 0
    last_accepted = 0
    tasks_done_unique_est = 0
    stopped_early = None
    ran = 0

    for i in range(1, args.cycles + 1):
        ts = utc()
        rc, out = runner()
        ran = i
        info = classify_cycle(rc, out)
        if rc == 0:
            cycles_exit0 += 1

        # accepted_cum growth estimates unique work when steps parse failed
        acc = info.get("accepted_cum")
        if acc is not None and acc > last_accepted:
            delta = acc - last_accepted
            tasks_done_unique_est += delta
            if not info["with_work"]:
                info["with_work"] = True
                info["idle"] = False
            last_accepted = acc
        elif info["with_work"]:
            tasks_done_unique_est += max(1, info["steps_this_wake"])

        if info["with_work"]:
            cycles_with_work += 1
            consecutive_idle = 0
        elif info["idle"]:
            cycles_idle += 1
            consecutive_idle += 1
        else:
            consecutive_idle = 0

        row = {
            "utc": ts,
            "cycle": i,
            "exit": rc,
            "steps_this_wake": info["steps_this_wake"],
            "accepted_cum": info.get("accepted_cum"),
            "with_work": info["with_work"],
            "idle": info["idle"],
            "cp_parsed": info["cp_parsed"],
            "sha_full": sha_full,
        }
        log(
            f"{ts} cycle={i} exit={rc} with_work={info['with_work']} "
            f"idle={info['idle']} steps={info['steps_this_wake']}"
        )
        tail = out.strip()[-500:] if out else ""
        if tail:
            log(tail)
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

        if consecutive_idle >= args.idle_stop_after and args.idle_policy != "continue":
            if args.idle_policy == "stop":
                stopped_early = f"idle_stop_after_{args.idle_stop_after}"
                log(f"idle_policy=stop triggered at cycle={i}")
                break
            if args.idle_policy == "reseed":
                try:
                    n = seed_tasks(args.reseed_batch, prefix=f"soak-reseed-{i}")
                    log(f"idle_policy=reseed added {n} tasks")
                    consecutive_idle = 0
                except Exception as e:
                    log(f"reseed error: {e}")
                    stopped_early = "reseed_failed"
                    break

        if i < args.cycles and stopped_early is None:
            time.sleep(args.interval)

    metrics = {
        "utc_end": utc(),
        "sha_short": sha_short,
        "sha_full": sha_full,
        "via_l1": args.via_l1,
        "idle_policy": args.idle_policy,
        "cycles_planned": args.cycles,
        "cycles_ran": ran,
        "cycles_exit0": cycles_exit0,
        "cycles_with_work": cycles_with_work,
        "cycles_idle": cycles_idle,
        "tasks_done_unique_est": tasks_done_unique_est,
        "stopped_early": stopped_early,
        "note": (
            "cycles_exit0 is process success only; "
            "business progress is cycles_with_work / tasks_done_unique_est. "
            "Do not claim business soak PASS from exit0 alone."
        ),
        "evidence_binding": "medium_plus",
        "paths": {
            "log": str(log_path),
            "summary_jsonl": str(summary_path),
            "metrics_json": str(metrics_path),
        },
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    log(
        f"=== soak end {utc()} exit0={cycles_exit0}/{ran} "
        f"with_work={cycles_with_work} idle={cycles_idle} "
        f"tasks_est={tasks_done_unique_est} stopped_early={stopped_early} ==="
    )
    print(json.dumps(metrics, indent=2))
    print(f"Log: {log_path}")
    print(f"Summary: {summary_path}")
    print(f"Metrics: {metrics_path}")

    # Exit 0 only if every ran cycle exited 0; still not a business PASS claim.
    return 0 if cycles_exit0 == ran and ran > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
