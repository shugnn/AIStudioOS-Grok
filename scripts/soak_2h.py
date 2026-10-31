#!/usr/bin/env python3
"""Local soak runner (Windows-friendly).

Respects EMERGENCY_STOP; metrics in finally + checkpoint.
--max-wall-seconds: stop when monotonic wall exceeds limit (honest 24h bound).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_plane.emergency_stop import is_stopped, reason as stop_reason

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


def seed_tasks(n: int = 30, prefix: str | None = None) -> int:
    from control_plane.control_plane import ControlPlane
    from control_plane.store import FileStore
    from experiments.exp02_auto_loop.cp_driven_loop import STATE, ensure_goal

    batch = prefix or f"soak-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    store = FileStore(STATE)
    cp = ControlPlane(store)
    gid = ensure_goal(cp)
    created = 0
    for i in range(n):
        kind = "word_count" if i % 2 == 0 else "checksum"
        payload = {"text": f"soak task {batch} {i}"} if kind == "word_count" else {"n": i + 3}
        key = f"{batch}-{i}"
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
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_once_l1() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/l1_runner.py"), "--job", "auto_loop_once"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)},
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    objs: list[dict[str, Any]] = []
    if not text:
        return objs
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                o = json.loads(s)
                if isinstance(o, dict):
                    objs.append(o)
            except json.JSONDecodeError:
                pass
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            o = json.loads(text[start : end + 1])
            if isinstance(o, dict):
                objs.append(o)
    except json.JSONDecodeError:
        pass
    return objs


def _cp_fields_from_mapping(o: dict[str, Any]) -> dict[str, Any] | None:
    if "steps_this_wake" not in o and "experiment" not in o:
        return None
    try:
        steps = int(o.get("steps_this_wake") or 0)
    except (TypeError, ValueError):
        steps = 0
    accepted = None
    if "accepted" in o:
        try:
            accepted = int(o.get("accepted") or 0)
        except (TypeError, ValueError):
            accepted = None
    return {"steps": steps, "accepted": accepted, "parsed": True}


def _load_cp_from_l1_artifact(artifact_path: str | None) -> dict[str, Any] | None:
    if not artifact_path:
        return None
    p = Path(artifact_path)
    if not p.is_file():
        return None
    try:
        report = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for job in report.get("jobs") or []:
        tail = job.get("stdout_tail") or ""
        if not isinstance(tail, str):
            continue
        for o in _extract_json_objects(tail):
            got = _cp_fields_from_mapping(o)
            if got:
                return got
        try:
            start = tail.find("{")
            end = tail.rfind("}")
            if start >= 0 and end > start:
                got = _cp_fields_from_mapping(json.loads(tail[start : end + 1]))
                if got:
                    return got
        except json.JSONDecodeError:
            pass
    return None


def classify_cycle(rc: int, out: str) -> dict[str, Any]:
    steps = 0
    accepted = None
    found_cp = False
    artifact = None
    for o in _extract_json_objects(out):
        if o.get("artifact"):
            artifact = str(o["artifact"])
        got = _cp_fields_from_mapping(o)
        if got:
            found_cp = True
            steps = got["steps"]
            accepted = got["accepted"]
            break
    if not found_cp and artifact:
        loaded = _load_cp_from_l1_artifact(artifact)
        if loaded:
            found_cp = True
            steps = loaded["steps"]
            accepted = loaded["accepted"]
    if not found_cp:
        runners = sorted(
            (ROOT / "docs" / "progress").glob("runner-*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if runners:
            loaded = _load_cp_from_l1_artifact(str(runners[0]))
            if loaded:
                found_cp = True
                steps = loaded["steps"]
                accepted = loaded["accepted"]
                artifact = str(runners[0])
    with_work = steps > 0
    idle = (rc == 0) and (not with_work)
    return {
        "exit": rc,
        "steps_this_wake": steps,
        "accepted_cum": accepted,
        "with_work": with_work,
        "idle": idle,
        "cp_parsed": found_cp,
        "artifact": artifact,
    }


def write_metrics(
    path: Path,
    *,
    sha_short: str,
    sha_full: str,
    via_l1: bool,
    idle_policy: str,
    cycles_planned: int,
    cycles_ran: int,
    cycles_exit0: int,
    cycles_with_work: int,
    cycles_idle: int,
    tasks_done_unique_est: int,
    stopped_early: str | None,
    log_path: Path,
    summary_path: Path,
    final: bool,
    error: str | None = None,
    wall_elapsed_s: float | None = None,
    max_wall_seconds: int | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "utc_end": utc(),
        "sha_short": sha_short,
        "sha_full": sha_full,
        "via_l1": via_l1,
        "idle_policy": idle_policy,
        "cycles_planned": cycles_planned,
        "cycles_ran": cycles_ran,
        "cycles_exit0": cycles_exit0,
        "cycles_with_work": cycles_with_work,
        "cycles_idle": cycles_idle,
        "tasks_done_unique_est": tasks_done_unique_est,
        "stopped_early": stopped_early,
        "final": final,
        "wall_elapsed_s": wall_elapsed_s,
        "max_wall_seconds": max_wall_seconds,
        "note": (
            "cycles_exit0 is process success only; "
            "business progress is cycles_with_work / tasks_done_unique_est. "
            "Wall clock is wall_elapsed_s (monotonic), not cycle_count*interval. "
            "Do not claim business soak PASS from exit0 alone."
        ),
        "evidence_binding": "medium_plus",
        "paths": {
            "log": str(log_path),
            "summary_jsonl": str(summary_path),
            "metrics_json": str(path),
        },
    }
    if error:
        metrics["error"] = error
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    tmp.replace(path)
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=120)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--via-l1", action="store_true")
    ap.add_argument("--no-reset-seed", action="store_true")
    ap.add_argument("--idle-policy", choices=["continue", "stop", "reseed"], default="stop")
    ap.add_argument("--idle-stop-after", type=int, default=3)
    ap.add_argument("--reseed-batch", type=int, default=30)
    ap.add_argument("--metrics-every", type=int, default=10)
    ap.add_argument(
        "--max-wall-seconds",
        type=int,
        default=0,
        help="hard stop after this many monotonic seconds (0=disabled). e.g. 86400 for 24h",
    )
    args = ap.parse_args()

    seed_n = args.seed if args.seed is not None else max(args.cycles, 30)
    log_path = OUT / "soak.log"
    summary_path = OUT / "summary.jsonl"
    metrics_path = OUT / "metrics.json"
    sha_short = git_sha(short=True)
    sha_full = git_sha(short=False)
    t0 = time.monotonic()

    def log(msg: str) -> None:
        line = msg if msg.endswith("\n") else msg + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
        print(msg, flush=True)

    cycles_exit0 = 0
    cycles_with_work = 0
    cycles_idle = 0
    consecutive_idle = 0
    last_accepted = 0
    tasks_done_unique_est = 0
    stopped_early: str | None = None
    ran = 0
    fatal_error: str | None = None

    def wall() -> float:
        return time.monotonic() - t0

    def dump(final: bool) -> dict[str, Any]:
        return write_metrics(
            metrics_path,
            sha_short=sha_short,
            sha_full=sha_full,
            via_l1=args.via_l1,
            idle_policy=args.idle_policy,
            cycles_planned=args.cycles,
            cycles_ran=ran,
            cycles_exit0=cycles_exit0,
            cycles_with_work=cycles_with_work,
            cycles_idle=cycles_idle,
            tasks_done_unique_est=tasks_done_unique_est,
            stopped_early=stopped_early,
            log_path=log_path,
            summary_path=summary_path,
            final=final,
            error=fatal_error,
            wall_elapsed_s=round(wall(), 3),
            max_wall_seconds=args.max_wall_seconds or None,
        )

    try:
        log(
            f"=== soak start {utc()} sha={sha_short} sha_full={sha_full} "
            f"cycles={args.cycles} interval={args.interval} via_l1={args.via_l1} "
            f"seed={seed_n} idle_policy={args.idle_policy} "
            f"max_wall_seconds={args.max_wall_seconds} ==="
        )

        if is_stopped():
            stopped_early = "emergency_stop_before_start"
            fatal_error = stop_reason() or "EMERGENCY_STOP present"
            log(f"emergency_stop before start: {fatal_error}")
            return 3

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
                fatal_error = f"seed_error:{e}"
                return 1

        dump(final=False)
        runner = run_once_l1 if args.via_l1 else run_once_direct

        for i in range(1, args.cycles + 1):
            if args.max_wall_seconds > 0 and wall() >= args.max_wall_seconds:
                stopped_early = "max_wall_seconds"
                log(f"max_wall_seconds reached before cycle={i} wall={wall():.1f}s")
                break

            if is_stopped():
                stopped_early = "emergency_stop"
                fatal_error = stop_reason() or "EMERGENCY_STOP present"
                log(f"emergency_stop at cycle boundary before={i}: {fatal_error}")
                break

            ts = utc()
            rc, out = runner()
            ran = i
            info = classify_cycle(rc, out)
            if rc == 0:
                cycles_exit0 += 1
            elif rc == 3:
                stopped_early = "emergency_stop_l1"
                fatal_error = "l1_exit_3"
                log(f"{ts} cycle={i} L1 emergency_stop")
                with open(summary_path, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "utc": ts,
                                "cycle": i,
                                "exit": rc,
                                "with_work": False,
                                "idle": False,
                                "emergency_stop": True,
                                "sha_full": sha_full,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                break

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
                "artifact": info.get("artifact"),
                "sha_full": sha_full,
                "wall_s": round(wall(), 3),
            }
            log(
                f"{ts} cycle={i} exit={rc} with_work={info['with_work']} "
                f"idle={info['idle']} steps={info['steps_this_wake']} "
                f"cp_parsed={info['cp_parsed']} wall_s={row['wall_s']}"
            )
            tail = out.strip()[-400:] if out else ""
            if tail:
                log(tail)
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

            if args.metrics_every > 0 and (i % args.metrics_every == 0):
                dump(final=False)

            if consecutive_idle >= args.idle_stop_after and args.idle_policy != "continue":
                if args.idle_policy == "stop":
                    stopped_early = f"idle_stop_after_{args.idle_stop_after}"
                    log(f"idle_policy=stop triggered at cycle={i}")
                    break
                if args.idle_policy == "reseed":
                    try:
                        n = seed_tasks(args.reseed_batch)
                        log(f"idle_policy=reseed added {n} tasks")
                        consecutive_idle = 0
                    except Exception as e:
                        log(f"reseed error: {e}")
                        stopped_early = "reseed_failed"
                        fatal_error = f"reseed_error:{e}"
                        break

            if i < args.cycles and stopped_early is None:
                # sleep only remaining wall budget if limited
                sleep_for = args.interval
                if args.max_wall_seconds > 0:
                    remain = args.max_wall_seconds - wall()
                    if remain <= 0:
                        stopped_early = "max_wall_seconds"
                        log(f"max_wall_seconds during interval before next cycle wall={wall():.1f}s")
                        break
                    sleep_for = min(sleep_for, remain)
                time.sleep(sleep_for)

        if stopped_early and str(stopped_early).startswith("emergency"):
            return 3
        return 0 if cycles_exit0 == ran and ran > 0 else 1

    except KeyboardInterrupt:
        stopped_early = stopped_early or "keyboard_interrupt"
        fatal_error = "keyboard_interrupt"
        log(f"interrupted at cycle={ran}")
        return 130
    except Exception as e:
        stopped_early = stopped_early or "exception"
        fatal_error = f"{type(e).__name__}:{e}"
        log(f"fatal: {fatal_error}")
        return 1
    finally:
        metrics = dump(final=True)
        try:
            log(
                f"=== soak end {utc()} exit0={cycles_exit0}/{ran} "
                f"with_work={cycles_with_work} idle={cycles_idle} "
                f"tasks_est={tasks_done_unique_est} stopped_early={stopped_early} "
                f"wall_s={wall():.1f} final_metrics=1 ==="
            )
            print(json.dumps(metrics, indent=2))
            print(f"Log: {log_path}")
            print(f"Summary: {summary_path}")
            print(f"Metrics: {metrics_path}")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
