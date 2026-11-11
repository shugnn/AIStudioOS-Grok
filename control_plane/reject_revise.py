"""Orchestrate reject-then-revise without judging the candidate.

The Worker process and the Verifier process are separate operating-system
processes. This module does not import either role's module and does not call
a model API.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BLOCKED_TASK_IDS = frozenset(
    {
        "DS-T1-20261108",
        "DS-T2-20261110",
        "DS-T3-20261111",
    }
)

EXPECTED_WROTE = {
    "prepare_input": ["data/appts.csv"],
    "verify_v1": ["deliverables/verdict_v1.json"],
    "revise": ["deliverables/candidate_v2.json", "deliverables/revision_log.json"],
    "verify_v2": ["deliverables/verdict_v2.json"],
}

COST_RECORD = {
    "record_type": "blocked_pending_not_a_paid_run",
    "status": "BLOCKED",
    "blocked": True,
    "completed_paid_run": False,
    "paid_api_called": False,
    "a6": "A-6 / cost.json is blocked pending founder API authorization in the founder chat",
    "pending": "founder API authorization in the founder chat",
    "model": None,
    "calls": None,
    "prompt_tokens": None,
    "completion_tokens": None,
    "estimated_cny": None,
    "note": (
        "Unpaid run. No model API was called. Token counts and CNY were not measured "
        "and are null on purpose. This file is not a completed paid-run cost record."
    ),
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


def _spawn(argv: list[str], cwd: Path, env: dict[str, str]) -> tuple[dict, str, str, int, int]:
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=60)
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


def _file_info(path: Path) -> dict:
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def orchestrate(*, inbox: Path, repo_root: Path) -> dict:
    inbox = inbox.resolve()
    repo_root = repo_root.resolve()
    dispatch_path = inbox / "dispatch.json"
    if not dispatch_path.is_file():
        return {"ok": False, "error": "no_dispatch"}
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    tid = dispatch.get("task_id")
    if tid in BLOCKED_TASK_IDS or inbox.name in BLOCKED_TASK_IDS:
        return {"ok": False, "error": "refused_task_id", "task_id": tid}
    if dispatch.get("mode") != "reject_then_revise":
        return {"ok": False, "error": "not_reject_then_revise", "task_id": tid}
    if dispatch.get("paid") is not False or dispatch.get("network") is not False:
        return {"ok": False, "error": "refusing_paid_or_network_dispatch", "task_id": tid}

    contract = json.loads((inbox / "contract.json").read_text(encoding="utf-8"))
    required_rules = list(contract["rules"].keys())
    out = inbox / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "cost.json", COST_RECORD)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python = sys.executable
    script = str(repo_root / "scripts" / "worker_run_task.py")
    csv_path = inbox / "data" / "appts.csv"
    steps: list[dict] = []

    def fail(error: str, **extra) -> dict:
        evidence = {
            "task_id": tid,
            "parent_pid": os.getpid(),
            "a4": (
                "Verifier and Worker are separate operating-system processes. "
                "The Worker does not write verdict files. The Verifier does not write candidate_v2.json."
            ),
            "ok": False,
            "error": error,
            "steps": steps,
        }
        _write_json(out / "a4_step_evidence.json", evidence)
        return {"ok": False, "error": error, "task_id": tid, "steps": steps, **extra}

    def run_step(step: str, role: str, argv: list[str]) -> dict:
        started = utc()
        payload, stdout, stderr, exit_code, pid = _spawn(argv, repo_root, env)
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
        }
        if not record["ok"]:
            record["error"] = payload.get("error")
            record["stdout"] = stdout[-2000:]
            record["stderr"] = stderr[-2000:]
        steps.append(record)
        return record

    prepare = run_step(
        "prepare_input",
        "worker",
        [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "prepare_input"],
    )
    if not prepare["ok"]:
        return fail("prepare_input_failed", input_sha256=prepare.get("sha256"), input_bytes=prepare.get("bytes"))

    verify_v1 = run_step(
        "verify_v1",
        "verifier",
        [
            python,
            "-m",
            "control_plane.contract_verifier",
            "--candidate",
            str(inbox / "candidate_v1.json"),
            "--csv",
            str(csv_path),
            "--contract",
            str(inbox / "contract.json"),
            "--out",
            str(out / "verdict_v1.json"),
            "--step",
            "verify_v1",
        ],
    )
    if not verify_v1["ok"]:
        return fail("verify_v1_failed")
    verdict_v1 = json.loads((out / "verdict_v1.json").read_text(encoding="utf-8"))
    got_rules = [item["rule"] for item in verdict_v1.get("reasons", [])]
    if verdict_v1.get("verdict") != "REJECTED" or any(rule not in got_rules for rule in required_rules):
        return fail("v1_did_not_reject_every_frozen_rule", verdict_v1=verdict_v1.get("verdict"))

    revise = run_step(
        "revise",
        "worker",
        [python, script, "--task-id", tid, "--inbox", str(inbox), "--step", "revise"],
    )
    if not revise["ok"]:
        return fail("revise_failed")
    revision = json.loads((out / "revision_log.json").read_text(encoding="utf-8"))
    entries = revision.get("entries", [])
    if [entry.get("rule") for entry in entries] != got_rules or any(not entry.get("addressed") for entry in entries):
        return fail("revision_log_does_not_cover_verdict_reasons")

    verify_v2 = run_step(
        "verify_v2",
        "verifier",
        [
            python,
            "-m",
            "control_plane.contract_verifier",
            "--candidate",
            str(out / "candidate_v2.json"),
            "--csv",
            str(csv_path),
            "--contract",
            str(inbox / "contract.json"),
            "--out",
            str(out / "verdict_v2.json"),
            "--step",
            "verify_v2",
        ],
    )
    if not verify_v2["ok"]:
        return fail("verify_v2_failed")
    verdict_v2 = json.loads((out / "verdict_v2.json").read_text(encoding="utf-8"))
    if verdict_v2.get("verdict") != "ACCEPTED" or verdict_v2.get("checks") != len(required_rules):
        return fail("v2_not_accepted", verdict_v2=verdict_v2.get("verdict"))

    roles = [step["role"] for step in steps]
    pids = [step["pid"] for step in steps]
    if roles != ["worker", "verifier", "worker", "verifier"] or len(set(pids)) != 4 or os.getpid() in pids:
        return fail("worker_and_verifier_were_not_separate_steps")

    evidence = {
        "task_id": tid,
        "parent_pid": os.getpid(),
        "a4": (
            "Verifier and Worker are separate operating-system processes. "
            "The Worker does not write verdict files. The Verifier does not write candidate_v2.json. "
            "verify_v1 and verify_v2 are two invocations of control_plane.contract_verifier. "
            "prepare_input and revise are two invocations of scripts/worker_run_task.py."
        ),
        "paid_api_called": False,
        "ok": True,
        "steps": steps,
    }
    _write_json(out / "a4_step_evidence.json", evidence)
    run_status = {
        "task_id": tid,
        "kind": "observation-track submission",
        "claim": {
            "observation_track_acceptance": "NOT_CLAIMED",
            "l3_acceptance": "NOT_CLAIMED",
            "t4_acceptance": "NOT_CLAIMED",
            "production_7x24": "NOT_ACCEPTED",
            "l2_2_clock": "NOT_STARTED",
        },
        "paid_api_called": False,
        "a6_cost_json": "BLOCKED_PENDING_FOUNDER_API_AUTHORIZATION",
        "a6_note": COST_RECORD["a6"],
        "input": {
            "path": "data/appts.csv",
            "sha256": prepare.get("sha256"),
            "bytes": prepare.get("bytes"),
            "lines": prepare.get("lines"),
        },
        "product_verifier_verdict_v1": "REJECTED",
        "product_verifier_verdict_v2": "ACCEPTED",
        "product_verifier_checks_v2": verdict_v2["checks"],
        "a4_separate_steps": True,
        "note": (
            "product_verifier_verdict_v2 ACCEPTED is the contract judgment of candidate_v2. "
            "It is not observation-track acceptance and not production 7x24 acceptance."
        ),
    }
    _write_json(out / "run_status.json", run_status)
    hashed = [
        inbox / "data" / "appts.csv",
        out / "verdict_v1.json",
        out / "candidate_v2.json",
        out / "verdict_v2.json",
        out / "revision_log.json",
        out / "cost.json",
        out / "run_status.json",
        out / "a4_step_evidence.json",
    ]
    manifest = {
        "task_id": tid,
        "files": {path.resolve().relative_to(inbox).as_posix(): _file_info(path) for path in hashed},
    }
    _write_json(out / "manifest.json", manifest)
    return {
        "ok": True,
        "task_id": tid,
        "input_sha256": prepare.get("sha256"),
        "input_bytes": prepare.get("bytes"),
        "input_lines": prepare.get("lines"),
        "verdict_v1": "REJECTED",
        "verdict_v2": "ACCEPTED",
        "a6": "BLOCKED_PENDING_FOUNDER_API_AUTHORIZATION",
        "steps": [{"step": step["step"], "role": step["role"], "pid": step["pid"]} for step in steps],
    }
