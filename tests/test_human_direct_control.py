"""Human-direct-control minimal loop: start, authorize, status, run, emergency-stop.

The demo worker/verifier is scaffold. These tests only prove the host-side verbs
and one bounded offline goal, not autonomy or production 7x24.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_plane import GoalStatus, TaskStatus
from control_plane.cli import main as cli_main
from control_plane.emergency_stop import STOP_ENV
from control_plane.human_loop import ARTIFACT_DIR, SCAFFOLD_NOTICE
from control_plane.store import FileStore

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def stop_file(tmp_path, monkeypatch):
    path = tmp_path / "EMERGENCY_STOP"
    monkeypatch.setenv(STOP_ENV, str(path))
    if path.exists():
        path.unlink()
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "state.json"


@pytest.fixture
def artifact_cleanup():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    before = {p.resolve() for p in ARTIFACT_DIR.glob("*.json")}
    yield
    if ARTIFACT_DIR.exists():
        for p in ARTIFACT_DIR.glob("*.json"):
            if p.resolve() not in before:
                p.unlink()


def _cli(state: Path, argv: list[str]) -> tuple[int, str, str]:
    from io import StringIO
    from contextlib import redirect_stderr, redirect_stdout

    out, err = StringIO(), StringIO()
    code = 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            cli_main(["--state", str(state), *argv])
    except SystemExit as exc:
        code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def test_full_loop_completes_bounded_goal(state_path, stop_file, artifact_cleanup, capsys):
    code, out, err = _cli(state_path, ["start"])
    assert code == 0, err
    assert "[scaffold]" in out
    payload = json.loads(out[out.index("{") : out.rindex("}") + 1])
    goal_id = payload["goal_id"]
    assert len(payload["tasks"]) == 2
    assert all(t["status"] == "proposed" for t in payload["tasks"])

    code, out, err = _cli(state_path, ["status"])
    assert code == 0, err
    assert "Armed: False" in out
    assert goal_id in out
    assert "proposed" in out

    # run before authorize must not execute work
    code, out, err = _cli(state_path, ["run"])
    assert code == 0, err
    report = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert report["steps"] == 0
    assert report["needs_authorize"] == 2
    assert "Authorize proposed tasks" in out

    code, out, err = _cli(state_path, ["authorize"])
    assert code == 0, err
    auth = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert len(auth["approved"]) == 2
    assert not auth["blocked"]

    code, out, err = _cli(state_path, ["run"])
    assert code == 0, err
    report = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert report["scaffold"] is True
    assert report["steps"] == 2
    assert goal_id in report["completed_goal_ids"]
    assert all(item["status"] == "accepted" for item in report["log"])
    assert "Goal completed" in out

    code, out, err = _cli(state_path, ["status"])
    assert code == 0, err
    assert "[completed]" in out
    assert "Spent: $0.00" in out
    assert "Hard-stop: False" in out
    store = FileStore(state_path)
    goal = store.get_goal(goal_id)
    assert goal is not None
    assert goal.status == GoalStatus.COMPLETED
    tasks = store.list_tasks(goal_id)
    assert all(t.status == TaskStatus.ACCEPTED for t in tasks)
    for item in report["log"]:
        assert Path(item["artifact"]).is_file()


def test_emergency_stop_refuses_start_and_run(state_path, stop_file, artifact_cleanup):
    code, out, err = _cli(state_path, ["start"])
    assert code == 0, err
    _cli(state_path, ["authorize"])

    code, out, err = _cli(state_path, ["emergency-stop", "--reason", "founder halt"])
    assert code == 0, err
    assert stop_file.is_file()
    assert "founder halt" in stop_file.read_text(encoding="utf-8")

    code, out, err = _cli(state_path, ["status"])
    assert code == 0, err
    assert "Armed: True" in out
    assert "founder halt" in out

    code, out, err = _cli(state_path, ["run"])
    assert code == 3
    assert "emergency stop" in err.lower()

    code, out, err = _cli(state_path, ["start"])
    assert code == 3

    # no task should have been executed
    store = FileStore(state_path)
    tasks = store.list_tasks()
    assert tasks
    assert all(t.status == TaskStatus.APPROVED for t in tasks)

    code, out, err = _cli(state_path, ["clear-stop"])
    assert code == 0, err
    assert not stop_file.is_file()

    code, out, err = _cli(state_path, ["run"])
    assert code == 0, err
    report = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert report["steps"] == 2
    assert report["completed_goal_ids"]


def test_stop_halts_after_first_once_step(state_path, stop_file, artifact_cleanup):
    _cli(state_path, ["start"])
    _cli(state_path, ["authorize"])
    code, out, err = _cli(state_path, ["run", "--once"])
    assert code == 0, err
    report = json.loads(out[out.index("{") : out.rindex("}") + 1])
    assert report["steps"] == 1
    assert not report["completed_goal_ids"]

    _cli(state_path, ["emergency-stop", "--reason", "mid-loop"])
    code, out, err = _cli(state_path, ["run", "--once"])
    assert code == 3
    store = FileStore(state_path)
    statuses = {t.status for t in store.list_tasks()}
    assert TaskStatus.ACCEPTED in statuses
    assert TaskStatus.APPROVED in statuses


def test_user_guide_commands_via_subprocess(state_path, stop_file, artifact_cleanup):
    """The exact USER_GUIDE entrypoint: python -m control_plane ..."""
    env = {**os.environ, "PYTHONPATH": str(ROOT), STOP_ENV: str(stop_file)}
    base = [sys.executable, "-m", "control_plane", "--state", str(state_path)]

    r = subprocess.run(base + ["start"], cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert SCAFFOLD_NOTICE.split("]")[0] in r.stdout

    r = subprocess.run(base + ["status"], cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "Armed: False" in r.stdout

    r = subprocess.run(base + ["authorize"], cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    r = subprocess.run(base + ["run"], cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "Goal completed" in r.stdout

    r = subprocess.run(
        base + ["emergency-stop", "--reason", "guide"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    r = subprocess.run(base + ["run"], cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert r.returncode == 3
    r = subprocess.run(base + ["clear-stop"], cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
