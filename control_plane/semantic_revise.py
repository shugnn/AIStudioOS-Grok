"""Orchestrate T5 model-involved semantic revision.

The Worker and the Verifier run as separate operating-system processes.
This parent records the result. It does not judge the candidate and it
does not itself call a model API.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_WROTE = {
    "verify_input": [],
    "interpret_complaint": [
        "deliverables/interpretation.json",
        "deliverables/recount_plan.json",
        "deliverables/model_usage.json",
    ],
    "revise": ["deliverables/candidate_v4.json"],
    "verify": ["deliverables/verdict.json"],
}


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _relative_wrote(items: list, inbox: Path) -> list[str]:
    rels: list[str] = []
    inbox_resolved = inbox.resolve()
    for item in items or []:
        path = Path(str(item))
        if path.is_absolute():
            rels.append(path.resolve().relative_to(inbox_resolved).as_posix())
        else:
            rels.append(path.as_posix())
    return rels


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


def orchestrate(*, inbox: Path, repo_root: Path) -> dict:
    inbox = inbox.resolve()
    repo_root = repo_root.resolve()
    dispatch = json.loads((inbox / "dispatch.json").read_text(encoding="utf-8"))
    tid = dispatch.get("task_id")
    if dispatch.get("mode") != "model_involved_semantic_revision":
        return {"ok": False, "error": "not_model_involved_semantic_revision", "task_id": tid}
    if tid != "DS-T5-20261112":
        return {"ok": False, "error": "unexpected_task_id", "task_id": tid}

    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python = sys.executable
    script = str(repo_root / "scripts" / "worker_run_task.py")
    steps: list[dict] = []

    def fail(error: str, **extra) -> dict:
        evidence = {
            "task_id": tid,
            "parent_pid": os.getpid(),
            "ok": False,
            "error": error,
            "paid_api_called": any(step.get("step") == "interpret_complaint" for step in steps),
            "steps": steps,
        }
        _write_json(out / "step_evidence.json", evidence)
        return {"ok": False, "error": error, "task_id": tid, "steps": steps, **extra}

    def run_step(step: str, role: str, argv: list[str], timeout: int) -> dict:
        started = utc()
        payload, stdout, stderr, exit_code, pid = _spawn(argv, repo_root, env, timeout)
        finished = utc()
        wrote = _relative_wrote(payload.get("wrote") or [], inbox)
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
                and wrote == EXPECTED_WROTE[step]
            ),
            "wrote": wrote,
            "verdict": payload.get("verdict"),
            "sha256": payload.get("sha256"),
            "bytes": payload.get("bytes"),
            "lines": payload.get("lines"),
            "calls": payload.get("calls"),
            "estimated_cny": payload.get("estimated_cny"),
            "model": payload.get("model"),
        }
        if not record["ok"]:
            record["error"] = payload.get("error")
            record["stdout"] = (stdout or "")[-2000:]
            record["stderr"] = (stderr or "")[-2000:]
        steps.append(record)
        return record

    verify_input = run_step(
        "verify_input",
        "worker",
        [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "verify_input"],
        60,
    )
    if not verify_input["ok"]:
        return fail("verify_input_failed", input_sha256=verify_input.get("sha256"), input_bytes=verify_input.get("bytes"))

    interpret = run_step(
        "interpret_complaint",
        "worker",
        [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "interpret_complaint"],
        240,
    )
    if not interpret["ok"]:
        return fail("interpret_complaint_failed")

    revise = run_step(
        "revise",
        "worker",
        [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "revise"],
        60,
    )
    if not revise["ok"]:
        return fail("revise_failed")

    verify = run_step(
        "verify",
        "verifier",
        [
            python,
            "-m",
            "control_plane.semantic_verifier",
            "--inbox",
            str(inbox),
            "--out",
            str(out / "verdict.json"),
            "--step",
            "verify",
        ],
        60,
    )
    if not verify["ok"]:
        return fail("verify_failed")
    verdict = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    if verdict.get("verdict") != "ACCEPTED":
        return fail("verdict_not_accepted", product_verdict=verdict.get("verdict"))

    roles = [step["role"] for step in steps]
    pids = [step["pid"] for step in steps]
    if roles != ["worker", "worker", "worker", "verifier"] or len(set(pids)) != 4 or os.getpid() in pids:
        return fail("worker_and_verifier_were_not_separate_steps")

    usage = json.loads((out / "model_usage.json").read_text(encoding="utf-8"))
    evidence = {
        "task_id": tid,
        "parent_pid": os.getpid(),
        "note": (
            "Worker and Verifier are separate operating-system processes. "
            "The Worker does not write verdict.json. The Verifier does not write "
            "interpretation.json, recount_plan.json, candidate_v4.json, or model_usage.json."
        ),
        "paid_api_called": True,
        "ok": True,
        "steps": steps,
    }
    _write_json(out / "step_evidence.json", evidence)
    run_status = {
        "task_id": tid,
        "kind": "observation-track submission",
        "claim": {
            "observation_track_acceptance": "NOT_CLAIMED",
            "l3_semantic_revision_acceptance": "NOT_CLAIMED",
            "t5_acceptance": "NOT_CLAIMED",
            "production_7x24": "NOT_ACCEPTED",
            "l2_2_clock": "NOT_STARTED",
        },
        "paid_api_called": True,
        "founder_confirmation": "this chat, 2026-11-13 07:49 Asia/Shanghai, phrase 按 D-023 执行 T5",
        "model": usage.get("model"),
        "calls": usage.get("calls"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "estimated_cny": usage.get("estimated_cny"),
        "product_verifier_verdict": verdict.get("verdict"),
        "input": {
            "path": "data/appts.csv",
            "sha256": verify_input.get("sha256"),
            "bytes": verify_input.get("bytes"),
            "lines": verify_input.get("lines"),
        },
        "a4_separate_steps": True,
        "note": (
            "product_verifier_verdict ACCEPTED is the product Verifier judgment of this run. "
            "It is not observation-track acceptance and not production 7x24 acceptance."
        ),
    }
    _write_json(out / "run_status.json", run_status)
    cost = {
        "record_type": "completed_paid_run",
        "status": "COMPLETED",
        "blocked": False,
        "completed_paid_run": True,
        "paid_api_called": True,
        "model": usage.get("model"),
        "calls": usage.get("calls"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "estimated_cny": usage.get("estimated_cny"),
        "estimated_cny_exact": usage.get("estimated_cny_exact"),
        "tariff_window": usage.get("tariff_window"),
        "cap_cny": "5.00",
        "policy": "D-023",
        "pricing_source": usage.get("pricing_source"),
    }
    _write_json(out / "cost.json", cost)
    hashed = [
        inbox / "data" / "appts.csv",
        inbox / "candidate_v3.json",
        out / "interpretation.json",
        out / "recount_plan.json",
        out / "candidate_v4.json",
        out / "model_usage.json",
        out / "verdict.json",
        out / "cost.json",
        out / "run_status.json",
        out / "step_evidence.json",
    ]
    manifest = {
        "task_id": tid,
        "files": {path.resolve().relative_to(inbox).as_posix(): _file_info(path) for path in hashed},
    }
    _write_json(out / "manifest.json", manifest)
    return {
        "ok": True,
        "task_id": tid,
        "input_sha256": verify_input.get("sha256"),
        "input_bytes": verify_input.get("bytes"),
        "input_lines": verify_input.get("lines"),
        "verdict": verdict.get("verdict"),
        "model": usage.get("model"),
        "calls": usage.get("calls"),
        "estimated_cny": usage.get("estimated_cny"),
        "paid_api_called": True,
        "steps": [{"step": step["step"], "role": step["role"], "pid": step["pid"]} for step in steps],
    }
