#!/usr/bin/env python3
"""One-shot local health check for AIStudioOS-Grok ($0, no long soak).

Checks: imports, emergency stop module, L1 dry job, CP --once after reset seed=1,
then the L2-2 not-started scaffold (offline preflight + not-started fixture score).
Optionally runs the unit suite. That suite is not L2-2 acceptance.

Exit 0 only if all steps ok (and not emergency-stopped).
Exit 0 is overall_ok. It is not a gate PASS, it does not start the 72h clock,
and it does not launch the soak driver.

  py -3 scripts/health_check.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NOT_STARTED_FIXTURE = (
    Path("tests") / "fixtures" / "l2_2" / "scaffold_clock_not_started.json"
)
R2_RELATIVE = Path("docs") / "progress" / "l2_2" / "R2_CHECKLIST.md"
GATE_KEYS = ("can_start_clock", "can_accept_l2_2", "can_close_l2_2")
START_DECISIONS = {"given", "started", "approved"}


def step(name: str, ok: bool, detail: str = "", **extra: Any) -> dict:
    row = {"step": name, "ok": ok, "detail": detail, **extra}
    print(json.dumps(row, ensure_ascii=False))
    return row


def interpreter() -> str:
    """The interpreter that launched this process, else python3, else python."""
    exe = sys.executable
    if exe and Path(exe).is_file():
        return exe
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return "python3"


def _add(violations: list[str], name: str) -> None:
    if name not in violations:
        violations.append(name)


def _l2_modules() -> tuple[Any, Any]:
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import l2_2_preflight as preflight_mod
    import l2_2_score as score_mod

    return preflight_mod, score_mod


def _walk_claims(node: Any, violations: list[str]) -> None:
    """Fail closed on a nested PASS, ACCEPTED, start, or open gate.

    Honest reports mention those words inside refusal sentences. This walk
    reads claim fields only.
    """
    if isinstance(node, dict):
        if "l2_2_status" in node:
            status = node.get("l2_2_status")
            if not isinstance(status, str):
                _add(violations, "l2_2_status")
            else:
                upper = status.strip().upper().replace(" ", "_")
                if upper == "PASS" or upper.startswith("PASS"):
                    _add(violations, "forged_pass")
                elif upper == "ACCEPTED":
                    _add(violations, "forged_accept_status")
                elif upper != "NOT_STARTED":
                    _add(violations, "l2_2_status")
        if "clock_state" in node and node.get("clock_state") != "NOT_STARTED":
            _add(violations, "forged_clock_start")
        if node.get("clock_started") is True:
            _add(violations, "forged_clock_start")
        if "clock_effect" in node and node.get("clock_effect") != "none":
            _add(violations, "forged_clock_start")
        if node.get("soak_launched") is True or node.get("documented_soak_argv_executed") is True:
            _add(violations, "soak_launched")
        if "production_7x24" in node and node.get("production_7x24") != "NOT_ACCEPTED":
            _add(violations, "forged_production_accepted")
        if node.get("exit_0_is_gate_pass") is True or node.get("gate_result") == "PASS":
            _add(violations, "forged_pass")
        if node.get("verified") is True or node.get("supervision_verified") is True:
            _add(violations, "verified_claim")
        decision = node.get("start_decision")
        if isinstance(decision, str) and decision.strip().lower() in START_DECISIONS:
            _add(violations, "forged_start_decision")
        for key in GATE_KEYS:
            if node.get(key) is True:
                _add(violations, "forged_" + key)
        for value in node.values():
            _walk_claims(value, violations)
    elif isinstance(node, list):
        for item in node:
            _walk_claims(item, violations)


def l2_2_commands(root: Path | None = None) -> list[list[str]]:
    """Offline preflight and the not-started fixture score. No soak driver."""
    repo = root or ROOT
    exe = interpreter()
    return [
        [exe, str(repo / "scripts" / "l2_2_preflight.py")],
        [
            exe,
            str(repo / "scripts" / "l2_2_score.py"),
            "--capture",
            str(repo / NOT_STARTED_FIXTURE),
        ],
    ]


def pytest_command() -> list[str]:
    return [interpreter(), "-m", "pytest", "tests/", "-q"]


def _run_json(cmd: list[str]) -> tuple[int, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, {"ok": False, "error": type(exc).__name__}
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode if proc.returncode else 1, None


def assess_l2_2_offline(
    preflight_report: Any,
    score_report: Any,
    *,
    r2_text: str,
    preflight_exit: int,
    score_exit: int,
) -> dict[str, Any]:
    """Honest NOT_STARTED check. Gates in the result stay false.

    A scorer exit 0 on a started or INCOMPLETE bundle is not acceptance.
    """
    violations: list[str] = []
    r2_unfilled = False
    try:
        preflight_mod, score_mod = _l2_modules()
    except Exception as exc:
        _add(violations, "l2_import:" + type(exc).__name__)
        preflight_mod = None
        score_mod = None

    if preflight_exit != 0:
        _add(violations, "preflight_exit")
    if score_exit != 0:
        _add(violations, "score_exit")
    if not isinstance(preflight_report, dict):
        _add(violations, "preflight_unreadable")
    if not isinstance(score_report, dict):
        _add(violations, "score_unreadable")

    if preflight_mod is not None and isinstance(preflight_report, dict):
        if preflight_report.get("schema") != preflight_mod.SCHEMA:
            _add(violations, "preflight_schema")
        if preflight_report.get("report_kind") != "offline_preflight":
            _add(violations, "preflight_kind")
        if preflight_report.get("soak_launched") is not False:
            _add(violations, "soak_launched")
        if preflight_report.get("documented_soak_argv_executed") is not False:
            _add(violations, "soak_launched")
        if preflight_report.get("not_started_scaffold_intact") is not True:
            _add(violations, "scaffold_not_intact")
        source = preflight_report.get("source") if isinstance(preflight_report.get("source"), dict) else {}
        if source.get("collector_mode") != "offline_preflight":
            _add(violations, "preflight_not_offline")
        checks = preflight_report.get("checks") if isinstance(preflight_report.get("checks"), dict) else {}
        flags = checks.get("soak_flags") if isinstance(checks.get("soak_flags"), dict) else {}
        if flags.get("executed") is not False:
            _add(violations, "soak_launched")
        r2_row = checks.get("r2_checklist") if isinstance(checks.get("r2_checklist"), dict) else {}
        report_unfilled = r2_row.get("unfilled") is True and r2_row.get("start_decision") == "not_given"
        if not report_unfilled:
            _add(violations, "r2_report_not_blank")
        for name in preflight_mod.validate_report(preflight_report):
            if name in {"forged_can_start_clock", "forged_can_accept_l2_2", "forged_can_close_l2_2"}:
                _add(violations, name)
            elif name == "status":
                _add(violations, "l2_2_status")
            elif name == "clock_state":
                _add(violations, "forged_clock_start")
            elif name == "soak_launched":
                _add(violations, "soak_launched")
            elif name == "production_claim":
                _add(violations, "forged_production_accepted")
            elif name in {"exit_0_claim", "gate_result"}:
                _add(violations, "forged_pass")
            elif name == "r2_implies_start":
                _add(violations, "forged_start_decision")
            else:
                _add(violations, "preflight:" + name)
        _walk_claims(preflight_report, violations)

    if score_mod is not None and isinstance(score_report, dict):
        if score_report.get("schema") != score_mod.SCHEMA_REPORT:
            _add(violations, "score_schema")
        if score_report.get("l2_2_status") != "NOT_STARTED":
            if score_report.get("l2_2_status") == "PASS":
                _add(violations, "forged_pass")
            else:
                _add(violations, "l2_2_status")
        if score_report.get("clock_state") != "NOT_STARTED":
            _add(violations, "forged_clock_start")
        source = score_report.get("source") if isinstance(score_report.get("source"), dict) else {}
        if source.get("collector_mode") != "offline_score":
            _add(violations, "score_not_offline")
        if source.get("synthetic") is not True:
            _add(violations, "not_scaffold_fixture")
        for name in score_mod.validate_report(score_report):
            if name == "forged_pass":
                _add(violations, "forged_pass")
            elif name == "forged_accept":
                _add(violations, "forged_can_accept_l2_2")
            elif name == "forged_close":
                _add(violations, "forged_can_close_l2_2")
            elif name == "forged_clock_start":
                _add(violations, "forged_can_start_clock")
            elif name == "production_claim":
                _add(violations, "forged_production_accepted")
            elif name == "status":
                _add(violations, "l2_2_status")
            else:
                _add(violations, "score:" + name)
        _walk_claims(score_report, violations)

    if preflight_mod is not None:
        classified = preflight_mod.classify_r2(r2_text)
        r2_unfilled = (
            classified.get("unfilled") is True
            and classified.get("start_decision") == "not_given"
            and classified.get("ok") is True
        )
        if not r2_unfilled:
            _add(violations, "r2_checklist_not_blank")
        if isinstance(preflight_report, dict):
            checks = preflight_report.get("checks") if isinstance(preflight_report.get("checks"), dict) else {}
            r2_row = checks.get("r2_checklist") if isinstance(checks.get("r2_checklist"), dict) else {}
            report_unfilled = r2_row.get("unfilled") is True and r2_row.get("start_decision") == "not_given"
            if r2_unfilled != report_unfilled:
                _add(violations, "r2_disagrees")

    ok = not violations
    return {
        "ok": ok,
        "violations": violations,
        "l2_2_status": "NOT_STARTED" if ok else "WITHHELD",
        "clock_state": "NOT_STARTED" if ok else "WITHHELD",
        "soak_launched": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "r2_unfilled": r2_unfilled,
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
        "pytest_is_l2_2_acceptance": False,
    }


def run_l2_2_assessment(root: Path | None = None) -> dict[str, Any]:
    """Subprocess the preflight and the not-started fixture. Does not launch soak."""
    repo = root or ROOT
    commands = l2_2_commands(repo)
    preflight_exit, preflight_report = _run_json(commands[0])
    score_exit, score_report = _run_json(commands[1])
    checklist = repo / R2_RELATIVE
    r2_text = checklist.read_text(encoding="utf-8") if checklist.is_file() else ""
    return assess_l2_2_offline(
        preflight_report,
        score_report,
        r2_text=r2_text,
        preflight_exit=preflight_exit,
        score_exit=score_exit,
    )


def l2_2_offline_step() -> dict:
    assessment = run_l2_2_assessment()
    detail = "not_started_scaffold" if assessment["ok"] else ",".join(assessment["violations"])
    return step(
        "l2_2_offline",
        assessment["ok"] is True,
        detail[:500],
        l2_2_status=assessment["l2_2_status"],
        clock_state=assessment["clock_state"],
        soak_launched=False,
        production_7x24="NOT_ACCEPTED",
        can_start_clock=False,
        can_accept_l2_2=False,
        can_close_l2_2=False,
        r2_unfilled=assessment["r2_unfilled"],
        gate_result="NOT_A_GATE",
        exit_0_is_gate_pass=False,
        violations=assessment["violations"],
    )


def run_pytest_step() -> dict:
    """Unit suite. A green suite does not accept L2-2 and does not start the clock."""
    base = {
        "is_l2_2_acceptance": False,
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "production_7x24": "NOT_ACCEPTED",
        "soak_launched": False,
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
    }
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return step("pytest_suite", True, "skipped_already_inside_pytest_not_an_acceptance", **base)
    if os.environ.get("HEALTH_CHECK_SKIP_PYTEST") == "1":
        return step("pytest_suite", True, "skipped_by_env_not_an_acceptance", **base)
    cmd = pytest_command()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    # Child health checks must not start another suite.
    env["HEALTH_CHECK_SKIP_PYTEST"] = "1"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return step("pytest_suite", False, "pytest_not_run:" + type(exc).__name__, **base)
    lines = [line for line in (proc.stdout or proc.stderr or "").splitlines() if line.strip()]
    last = lines[-1] if lines else ""
    return step(
        "pytest_suite",
        proc.returncode == 0,
        ("unit_suite_not_l2_2_acceptance:" + last)[:500],
        **base,
    )


def summarize(results: list[dict], overall: bool) -> dict[str, Any]:
    """This process never grants a start, an accept, or a close."""
    l2 = next((row for row in results if row.get("step") == "l2_2_offline"), None)
    if l2 is None:
        status, clock, checked, r2_unfilled = "NOT_STARTED", "NOT_STARTED", False, None
    else:
        status = l2.get("l2_2_status", "WITHHELD")
        clock = l2.get("clock_state", "WITHHELD")
        checked = l2.get("ok") is True
        r2_unfilled = l2.get("r2_unfilled")
    return {
        "overall_ok": overall,
        "l2_2_status": status,
        "clock_state": clock,
        "l2_2_checked": checked,
        "soak_launched": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "r2_unfilled": r2_unfilled,
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
        "pytest_is_l2_2_acceptance": False,
        "results": results,
    }


def _emit(results: list[dict], overall: bool) -> None:
    print(json.dumps(summarize(results, overall), indent=2, ensure_ascii=False))


def main() -> int:
    results: list[dict] = []

    try:
        from control_plane.emergency_stop import is_stopped, STOP_PATH

        if is_stopped():
            results.append(step("emergency_stop", False, f"armed at {STOP_PATH}"))
            _emit(results, False)
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
        env={**dict(os.environ), "PYTHONPATH": str(ROOT)},
    )
    results.append(
        step(
            "l1_dry_protocol",
            r.returncode == 0,
            (r.stdout or r.stderr or "")[-200:],
        )
    )

    env = {**dict(os.environ), "PYTHONPATH": str(ROOT)}
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

    results.append(l2_2_offline_step())
    results.append(run_pytest_step())

    overall = all(x["ok"] for x in results)
    _emit(results, overall)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
