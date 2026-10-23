#!/usr/bin/env python3
"""Exp-01: ScriptManager baseline closed loop (deterministic, zero paid API).

NOT an LLM Manager run. All planning is hard-coded script logic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from control_plane import ControlPlane, BudgetExceeded, PermissionDenied, TaskStatus
from control_plane.store import FileStore

WORK = Path(__file__).resolve().parent
WS = WORK / "workspace"
LOGS = WORK / "logs"
STATE = WORK / "cp_state.json"
LOGS.mkdir(parents=True, exist_ok=True)
WS.mkdir(parents=True, exist_ok=True)

INTERVENTIONS = []


def log(msg: str):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line)
    with open(LOGS / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def script_manager_propose(cp: ControlPlane, goal_id: str):
    """Deterministic next-task generation from goal gap (ScriptManager)."""
    tasks = cp.list_tasks(goal_id)
    accepted_titles = {t.title for t in tasks if t.status == TaskStatus.ACCEPTED}
    plan = [
        ("scaffold package", "Create wcmini package structure and __main__", 0.0),
        ("implement core", "Implement line/word/byte counting logic", 0.0),
        ("add tests", "Add at least 5 pytest unit tests", 0.0),
        ("verify acceptance", "Run full acceptance criteria checks", 0.0),
    ]
    for title, desc, est in plan:
        if title not in accepted_titles:
            # skip if already open
            open_titles = {t.title for t in tasks if t.status not in (
                TaskStatus.ACCEPTED, TaskStatus.CANCELLED)}
            if title in open_titles:
                for t in tasks:
                    if t.title == title and t.status not in (TaskStatus.ACCEPTED, TaskStatus.CANCELLED):
                        return t
            return cp.propose_task(
                goal_id, title, desc,
                proposed_by="script_manager",
                estimated_cost_usd=est,
                idempotency_key=f"exp01:{title}",
            )
    return None


def worker_execute(cp: ControlPlane, task) -> str:
    """Scripted worker: writes files only under workspace; no network."""
    cp.check_permission("file_write", path=str(WS / "wcmini"))
    artifact = WS / "wcmini"

    if task.title == "scaffold package":
        (artifact).mkdir(parents=True, exist_ok=True)
        (artifact / "__init__.py").write_text('"""wcmini - tiny word count CLI."""\n__version__ = "0.1.0"\n')
        (artifact / "__main__.py").write_text(
            "from .cli import main\nif __name__ == '__main__':\n    raise SystemExit(main())\n"
        )
        (artifact / "cli.py").write_text(
            "def main(argv=None):\n    print('wcmini stub')\n    return 0\n"
        )
        return str(artifact)

    if task.title == "implement core":
        (artifact / "core.py").write_text('''\
from pathlib import Path

def count_file(path: str | Path) -> tuple[int, int, int]:
    data = Path(path).read_bytes()
    lines = data.count(b"\\n")
    # words: whitespace-separated tokens in text
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    words = len(text.split())
    bytes_ = len(data)
    return lines, words, bytes_
''')
        (artifact / "cli.py").write_text('''\
import argparse
import sys
from .core import count_file

def main(argv=None):
    p = argparse.ArgumentParser(prog="wcmini", description="Tiny word count CLI")
    p.add_argument("files", nargs="*", help="files to count")
    args = p.parse_args(argv)
    if not args.files:
        p.print_help()
        return 0
    total = (0, 0, 0)
    for f in args.files:
        try:
            l, w, b = count_file(f)
        except FileNotFoundError:
            print(f"wcmini: {f}: No such file", file=sys.stderr)
            return 1
        print(f"{l:8d} {w:8d} {b:8d} {f}")
        total = (total[0]+l, total[1]+w, total[2]+b)
    if len(args.files) > 1:
        print(f"{total[0]:8d} {total[1]:8d} {total[2]:8d} total")
    return 0
''')
        return str(artifact)

    if task.title == "add tests":
        tests = WORK / "workspace" / "test_wcmini.py"
        tests.write_text('''\
import subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sample.txt"
sys.path.insert(0, str(ROOT))

from wcmini.core import count_file

def test_count_file_lines_words_bytes():
    l, w, b = count_file(FIX)
    assert l == 3
    assert w == 7
    assert b > 0

def test_count_empty(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("")
    l, w, b = count_file(f)
    assert l == 0 and w == 0 and b == 0

def test_cli_help():
    r = subprocess.run([sys.executable, "-m", "wcmini", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0
    assert "usage" in r.stdout.lower() or "word" in r.stdout.lower() or "wcmini" in r.stdout.lower()

def test_cli_on_fixture():
    r = subprocess.run([sys.executable, "-m", "wcmini", str(FIX)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0
    parts = r.stdout.split()
    assert int(parts[0]) == 3
    assert int(parts[1]) == 7

def test_cli_missing_file():
    r = subprocess.run([sys.executable, "-m", "wcmini", "no_such_file_xyz"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0

def test_version_import():
    import wcmini
    assert hasattr(wcmini, "__version__")
''')
        return str(tests)

    if task.title == "verify acceptance":
        return str(artifact)

    raise RuntimeError(f"unknown task {task.title}")


def independent_verifier(cp: ControlPlane, task) -> tuple[bool, str]:
    """Separate from worker: runs pytest / acceptance checks only."""
    if task.title in ("scaffold package", "implement core"):
        path = WS / "wcmini"
        if not path.exists():
            return False, "artifact missing"
        return True, f"{task.title} artifact present"

    if task.title == "add tests":
        r = subprocess.run(
            [sys.executable, "-m", "pytest", str(WS / "test_wcmini.py"), "-v"],
            cwd=str(WS), capture_output=True, text=True,
        )
        (LOGS / "pytest_add_tests.txt").write_text(r.stdout + "\n" + r.stderr)
        ok = r.returncode == 0
        return ok, f"pytest rc={r.returncode}\n{r.stdout[-500:]}"

    if task.title == "verify acceptance":
        checks = []
        # help
        r1 = subprocess.run(
            [sys.executable, "-m", "wcmini", "--help"],
            cwd=str(WS), capture_output=True, text=True,
        )
        checks.append(("help", r1.returncode == 0))
        # fixture counts
        fix = WORK / "fixtures" / "sample.txt"
        r2 = subprocess.run(
            [sys.executable, "-m", "wcmini", str(fix)],
            cwd=str(WS), capture_output=True, text=True,
        )
        ok2 = r2.returncode == 0 and "3" in r2.stdout
        checks.append(("fixture", ok2))
        # pytest all
        r3 = subprocess.run(
            [sys.executable, "-m", "pytest", str(WS / "test_wcmini.py"), "-q"],
            cwd=str(WS), capture_output=True, text=True,
        )
        (LOGS / "pytest_final.txt").write_text(r3.stdout + "\n" + r3.stderr)
        checks.append(("pytest", r3.returncode == 0))
        # permission denies
        denied = []
        try:
            cp.check_permission("network")
        except PermissionDenied:
            denied.append("network")
        try:
            cp.check_permission("git_push")
        except PermissionDenied:
            denied.append("git_push")
        checks.append(("perm_deny", set(denied) == {"network", "git_push"}))

        ok = all(c[1] for c in checks)
        detail = json.dumps(checks)
        return ok, detail

    return False, "no verifier rule"


def test_idempotency(cp, goal_id):
    t1 = cp.propose_task(goal_id, "scaffold package", "x", idempotency_key="exp01:scaffold package")
    t2 = cp.propose_task(goal_id, "scaffold package", "x", idempotency_key="exp01:scaffold package")
    return t1.id == t2.id


def test_budget_block(cp, goal_id):
    t = cp.propose_task(goal_id, "expensive", "should block", estimated_cost_usd=999.0,
                        idempotency_key="exp01:expensive-block-test")
    try:
        cp.approve_task(t.id)
        return False, "should have blocked"
    except BudgetExceeded:
        t2 = cp.store.get_task(t.id)
        return t2.status == TaskStatus.BLOCKED, t2.block_reason or ""


def main():
    if STATE.exists():
        STATE.unlink()
    for p in STATE.parent.glob("cp_state.*"):
        p.unlink(missing_ok=True)

    cp = ControlPlane(store=FileStore(STATE))
    goal = cp.create_goal(
        title="Build a tiny word-count CLI",
        description="wcmini with tests; Exp-01 ScriptManager baseline",
        acceptance_criteria=[
            "python -m wcmini --help works",
            "correct counts on fixture",
            ">=5 pytest tests pass",
            "code under workspace/",
            "no network/git_push during run",
        ],
        budget_usd=5.0,
    )
    log(f"GOAL {goal.id}")

    # Idempotency check
    idem_ok = test_idempotency(cp, goal.id)
    log(f"IDEMPOTENCY {idem_ok}")

    steps = 0
    max_steps = 12
    while steps < max_steps:
        steps += 1
        task = script_manager_propose(cp, goal.id)
        if task is None:
            log("NO_MORE_TASKS")
            break
        log(f"PROPOSED {task.id} {task.title} status={task.status.value}")

        if task.status == TaskStatus.PROPOSED:
            try:
                task = cp.approve_task(task.id)
            except BudgetExceeded as e:
                log(f"BLOCKED {e}")
                INTERVENTIONS.append("budget_block")
                break
        if task.status == TaskStatus.CANCELLED:
            log(f"CANCELLED {task.id} stop")
            break
        if task.status != TaskStatus.APPROVED:
            if task.status == TaskStatus.REJECTED:
                if task.retry_count >= task.max_retries:
                    log(f"MAX_RETRIES {task.id}")
                    break
                try:
                    task = cp.approve_task(task.id)
                except BudgetExceeded:
                    break
            else:
                continue

        task = cp.mark_running(task.id)
        log(f"RUNNING {task.id}")
        artifact = worker_execute(cp, task)
        task = cp.submit_for_verification(task.id, artifact)
        ok, feedback = independent_verifier(cp, task)
        log(f"VERIFY {task.id} ok={ok} {feedback[:200]}")
        if ok:
            cp.accept_task(task.id, feedback=feedback, cost_usd=0.0, cost_tokens=0)
            log(f"ACCEPTED {task.id}")
        else:
            cp.reject_task(task.id, feedback=feedback)
            log(f"REJECTED {task.id}")

    # Budget block demo
    b_ok, b_reason = test_budget_block(cp, goal.id)
    log(f"BUDGET_BLOCK_TEST {b_ok} {b_reason}")

    # Checkpoint / recovery simulation
    ckpt = cp.create_checkpoint(goal.id, "pre_crash")
    log(f"CHECKPOINT {ckpt.id}")
    # reload store
    cp2 = ControlPlane(store=FileStore(STATE))
    latest = cp2.restore_from_latest(goal.id)
    recovered_tasks = cp2.list_tasks(goal.id)
    accepted = [t for t in recovered_tasks if t.status == TaskStatus.ACCEPTED]
    log(f"RECOVERY ok={latest is not None} accepted_count={len(accepted)}")

    # Final goal check
    all_titles = {t.title for t in accepted}
    needed = {"scaffold package", "implement core", "add tests", "verify acceptance"}
    done = needed <= all_titles
    if done:
        cp2.complete_goal(goal.id)
    log(f"GOAL_COMPLETE {done}")
    log(f"INTERVENTIONS {len(INTERVENTIONS)} {INTERVENTIONS}")
    log(f"BUDGET {cp2.get_budget().to_dict()}")

    results = {
        "goal_id": goal.id,
        "accepted": [t.title for t in accepted],
        "goal_complete": done,
        "idempotency": idem_ok,
        "budget_block_test": b_ok,
        "recovery_ok": latest is not None,
        "interventions": INTERVENTIONS,
        "budget": cp2.get_budget().to_dict(),
        "manager": "script_manager",
        "commit_note": "see git log",
    }
    (WORK / "results.json").write_text(json.dumps(results, indent=2))
    log("WROTE results.json")
    return 0 if done and idem_ok and b_ok else 1


if __name__ == "__main__":
    sys.exit(main())
