"""Orchestrate T6 bounded self-iteration.

The Worker and the Verifier run as separate operating-system processes.
This parent records scores, costs, and stop conditions. It does not itself
call a model API and it does not score R1-R5.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from control_plane.deepseek_client import format_cny

CAP_CNY = Decimal("5.00")


def format_total_cny(amount: Decimal, parts: list[Decimal] | None = None) -> str:
    """Format a summed cost so it stays consistent with per-round cost_cny (A-6)."""
    if parts:
        displayed = sum((Decimal(format_cny(part)) for part in parts), Decimal("0"))
        text = format(displayed.quantize(Decimal("0.0000001")), "f").rstrip("0").rstrip(".")
        return text if text else "0.00"
    two = amount.quantize(Decimal("0.01"))
    if amount == 0:
        return "0.00"
    if two != amount:
        text = format(amount.quantize(Decimal("0.0000001")), "f").rstrip("0").rstrip(".")
        return text if text else "0.00"
    return f"{two:.2f}"


DEFAULT_MAX_ROUNDS = 8
DEFAULT_NO_IMPROVE_LIMIT = 2


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decide_stop(*, passed: int, rounds: int, no_improve_streak: int, max_rounds: int, no_improve_limit: int) -> str | None:
    if passed >= 5:
        return "SCORE_5"
    if rounds >= max_rounds:
        return "ROUNDS_8" if max_rounds == DEFAULT_MAX_ROUNDS else "ROUNDS_8"
    if no_improve_streak >= no_improve_limit:
        return "NO_IMPROVEMENT"
    return None


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _file_info(path: Path) -> dict:
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _spawn(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> tuple[dict, str, str, int, int]:
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return (
            {"ok": False, "error": "timeout", "pid": proc.pid},
            stdout or "",
            stderr or "",
            proc.returncode if proc.returncode is not None else 1,
            proc.pid,
        )
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "error": "unparseable_stdout"}
    if not isinstance(payload, dict):
        payload = {"ok": False, "error": "stdout_not_object"}
    return payload, stdout or "", stderr or "", proc.returncode if proc.returncode is not None else 1, proc.pid


def _reset_deliverables(out: Path) -> None:
    if not out.exists():
        out.mkdir(parents=True, exist_ok=True)
        return
    keep = {"README.md"}
    for path in sorted(out.rglob("*"), reverse=True):
        if path.is_file() and path.name not in keep:
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    out.mkdir(parents=True, exist_ok=True)


def orchestrate(*, inbox: Path, repo_root: Path, max_rounds: int = DEFAULT_MAX_ROUNDS, no_improve_limit: int = DEFAULT_NO_IMPROVE_LIMIT) -> dict:
    inbox = inbox.resolve()
    repo_root = repo_root.resolve()
    dispatch = json.loads((inbox / "dispatch.json").read_text(encoding="utf-8"))
    tid = dispatch.get("task_id")
    if dispatch.get("mode") != "bounded_self_iteration_l4":
        return {"ok": False, "error": "not_bounded_self_iteration_l4", "task_id": tid}
    if tid != "DS-T6-20261114":
        return {"ok": False, "error": "unexpected_task_id", "task_id": tid}

    out = inbox / "deliverables"
    _reset_deliverables(out)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python = sys.executable
    script = str(repo_root / "scripts" / "worker_run_task.py")
    steps: list[dict] = []
    iterations: list[dict] = []
    exact_costs: list[Decimal] = []

    def fail(error: str, **extra) -> dict:
        evidence = {
            "task_id": tid,
            "parent_pid": os.getpid(),
            "ok": False,
            "error": error,
            "paid_api_called": any(step.get("step") == "propose_fix" and step.get("ok") for step in steps),
            "steps": steps,
        }
        _write_json(out / "step_evidence.json", evidence)
        return {"ok": False, "error": error, "task_id": tid, "steps": steps, "iterations": iterations, **extra}

    def run_cmd(step: str, role: str, argv: list[str], timeout: int) -> dict:
        started = utc()
        payload, stdout, stderr, exit_code, pid = _spawn(argv, repo_root, env, timeout)
        finished = utc()
        record = {
            "step": step,
            "role": role,
            "argv": argv,
            "pid": pid,
            "reported_pid": payload.get("pid"),
            "exit_code": exit_code,
            "started_utc": started,
            "finished_utc": finished,
            "ok": bool(
                payload.get("ok")
                and exit_code == 0
                and payload.get("role") == role
                and payload.get("step") == step
                and payload.get("pid") == pid
            ),
            "wrote": payload.get("wrote") or [],
            "score": payload.get("score"),
            "passed": payload.get("passed"),
            "failing": payload.get("failing"),
            "rule_targeted": payload.get("rule_targeted"),
            "estimated_cny": payload.get("estimated_cny"),
            "estimated_cny_exact": payload.get("estimated_cny_exact"),
            "model": payload.get("model"),
            "prompt_tokens": payload.get("prompt_tokens"),
            "completion_tokens": payload.get("completion_tokens"),
            "total_tokens": payload.get("total_tokens"),
        }
        if not record["ok"]:
            record["error"] = payload.get("error")
            record["stdout"] = (stdout or "")[-2000:]
            record["stderr"] = (stderr or "")[-2000:]
        steps.append(record)
        return record

    prepare = run_cmd(
        "prepare_input",
        "worker",
        [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "prepare_input"],
        60,
    )
    if not prepare["ok"]:
        return fail("prepare_input_failed")

    verify_input = run_cmd(
        "verify_input",
        "worker",
        [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "verify_input"],
        60,
    )
    if not verify_input["ok"]:
        return fail("verify_input_failed", input_sha256=verify_input.get("sha256") if False else None)

    initial = run_cmd(
        "score",
        "verifier",
        [python, "-m", "control_plane.iteration_verifier", "--inbox", str(inbox), "--step", "score", "--round", "0"],
        60,
    )
    if not initial["ok"]:
        return fail("initial_score_failed")

    current_score = json.loads((out / "current_score.json").read_text(encoding="utf-8"))
    stop_reason = decide_stop(
        passed=int(current_score["passed"]),
        rounds=0,
        no_improve_streak=0,
        max_rounds=max_rounds,
        no_improve_limit=no_improve_limit,
    )
    no_improve_streak = 0
    total_tokens = 0

    while stop_reason is None:
        spent = sum(exact_costs, Decimal("0"))
        if spent >= CAP_CNY:
            return fail("cost_cap_reached", spent=format_cny(spent))
        propose = run_cmd(
            "propose_fix",
            "worker",
            [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "propose_fix"],
            240,
        )
        if not propose["ok"]:
            return fail("propose_fix_failed")
        exact = Decimal(str(propose.get("estimated_cny_exact") or propose.get("estimated_cny") or "0"))
        if spent + exact > CAP_CNY:
            return fail("estimated_cny_exceeds_d023_cap", spent=format_cny(spent + exact))
        exact_costs.append(exact)
        total_tokens += int(propose.get("total_tokens") or 0)

        apply_fix = run_cmd(
            "apply_fix",
            "worker",
            [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "apply_fix"],
            60,
        )
        if not apply_fix["ok"]:
            return fail("apply_fix_failed")

        round_no = int(json.loads((out / "current_round.json").read_text(encoding="utf-8"))["round"])
        is_last_possible = (round_no >= max_rounds)
        argv = [
            python, "-m", "control_plane.iteration_verifier",
            "--inbox", str(inbox), "--step", "score", "--round", str(round_no),
        ]
        # --final is decided after we know the score/stop; first score without final, then maybe re-run? 
        # We'll mark final after stop is known, with a follow-up --final call if needed.
        score_step = run_cmd("score", "verifier", argv, 60)
        if not score_step["ok"]:
            return fail("score_failed", round=round_no)

        after = json.loads((out / "current_score.json").read_text(encoding="utf-8"))
        before_passed = int(current_score["passed"])
        after_passed = int(after["passed"])
        improved = after_passed > before_passed
        no_improve_streak = 0 if improved else no_improve_streak + 1
        usage = json.loads((out / "rounds" / f"{round_no:02d}" / "model_usage.json").read_text(encoding="utf-8"))
        plan = json.loads((out / "rounds" / f"{round_no:02d}" / "plan.json").read_text(encoding="utf-8"))
        row = {
            "round": round_no,
            "rule_targeted": plan.get("rule_targeted"),
            "model_reasoning": plan.get("model_reasoning"),
            "score_before": current_score["score"],
            "score_after": after["score"],
            "cost_cny": usage.get("estimated_cny"),
            "cost_cny_exact": usage.get("estimated_cny_exact"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "model": usage.get("model"),
            "api_id": usage.get("api_id"),
            "tariff_window": usage.get("tariff_window"),
        }
        iterations.append(row)
        with (out / "iterations.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        current_score = after
        stop_reason = decide_stop(
            passed=after_passed,
            rounds=round_no,
            no_improve_streak=no_improve_streak,
            max_rounds=max_rounds,
            no_improve_limit=no_improve_limit,
        )
        if is_last_possible and stop_reason is None:
            stop_reason = "ROUNDS_8"

    # Final verifier write
    final_round = iterations[-1]["round"] if iterations else 0
    final = run_cmd(
        "score",
        "verifier",
        [
            python, "-m", "control_plane.iteration_verifier",
            "--inbox", str(inbox), "--step", "score",
            "--round", str(final_round), "--final",
        ],
        60,
    )
    if not final["ok"]:
        return fail("final_score_failed")

    final_candidate = json.loads((out / "current_candidate.json").read_text(encoding="utf-8"))
    _write_json(out / "final_candidate.json", final_candidate)
    total_exact = sum(exact_costs, Decimal("0"))
    goal_status = "ACHIEVED" if current_score["passed"] >= 5 else "PARTIAL"
    stop_report = {
        "stop_reason": stop_reason,
        "rounds": len(iterations),
        "final_score": current_score["score"],
        "goal_status": goal_status,
        "total_cost_cny": format_total_cny(total_exact, exact_costs),
        "total_tokens": total_tokens,
    }
    _write_json(out / "stop_report.json", stop_report)

    roles_ok = all(step["role"] in {"worker", "verifier"} for step in steps)
    pids = [step["pid"] for step in steps]
    if not roles_ok or os.getpid() in pids or len(steps) < 3:
        return fail("worker_and_verifier_were_not_separate_steps")

    evidence = {
        "task_id": tid,
        "parent_pid": os.getpid(),
        "note": (
            "Worker and Verifier are separate operating-system processes. "
            "The parent records stop conditions from Verifier scores. "
            "The parent does not score R1-R5 and does not call a model API."
        ),
        "paid_api_called": not bool(os.environ.get("AISTUDIOOS_CHAT_JSON_MOCK")),
        "ok": True,
        "steps": steps,
    }
    _write_json(out / "step_evidence.json", evidence)
    run_status = {
        "task_id": tid,
        "kind": "observation-track submission",
        "claim": {
            "observation_track_acceptance": "NOT_CLAIMED",
            "l4_bounded_self_iteration_acceptance": "NOT_CLAIMED",
            "t6_acceptance": "NOT_CLAIMED",
            "production_7x24": "NOT_ACCEPTED",
            "l2_2_clock": "NOT_STARTED",
        },
        "paid_api_called": evidence["paid_api_called"],
        "founder_confirmation": "this chat, 2026-11-14 14:03 Asia/Shanghai, phrase 按 D-023 执行 T6",
        "stop_reason": stop_reason,
        "rounds": len(iterations),
        "final_score": current_score["score"],
        "goal_status": goal_status,
        "total_cost_cny": format_total_cny(total_exact, exact_costs),
        "total_tokens": total_tokens,
        "input": {
            "path": "data/appts.csv",
            "sha256": hashlib.sha256((inbox / "data" / "appts.csv").read_bytes()).hexdigest(),
            "bytes": (inbox / "data" / "appts.csv").stat().st_size,
            "lines": (inbox / "data" / "appts.csv").read_bytes().count(b"\n"),
        },
        "note": (
            "final_score is the product Verifier score of this run. "
            "It is not observation-track acceptance and not production 7x24 acceptance."
        ),
    }
    _write_json(out / "run_status.json", run_status)
    cost = {
        "record_type": "completed_run",
        "status": "COMPLETED",
        "blocked": False,
        "completed_paid_run": evidence["paid_api_called"],
        "paid_api_called": evidence["paid_api_called"],
        "calls": len(iterations),
        "total_tokens": total_tokens,
        "estimated_cny": format_total_cny(total_exact, exact_costs),
        "estimated_cny_exact": format(total_exact, "f"),
        "cap_cny": "5.00",
        "policy": "D-023",
        "round_costs": [row.get("cost_cny_exact") or row.get("cost_cny") for row in iterations],
    }
    _write_json(out / "cost.json", cost)
    hashed = [
        inbox / "data" / "appts.csv",
        inbox / "candidate_v0.json",
        out / "iterations.jsonl",
        out / "final_candidate.json",
        out / "stop_report.json",
        out / "verifier_final.json",
        out / "cost.json",
        out / "run_status.json",
        out / "step_evidence.json",
    ]
    manifest = {
        "task_id": tid,
        "files": {path.resolve().relative_to(inbox).as_posix(): _file_info(path) for path in hashed if path.is_file()},
    }
    _write_json(out / "manifest.json", manifest)
    return {
        "ok": True,
        "task_id": tid,
        "stop_reason": stop_reason,
        "rounds": len(iterations),
        "final_score": current_score["score"],
        "goal_status": goal_status,
        "total_cost_cny": format_total_cny(total_exact, exact_costs),
        "total_tokens": total_tokens,
        "paid_api_called": evidence["paid_api_called"],
    }
