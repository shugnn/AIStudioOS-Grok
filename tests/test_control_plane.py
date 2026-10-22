"""Unit tests for the thin Control Plane (Phase 1)."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_plane import (
    ControlPlane,
    BudgetExceeded,
    PermissionDenied,
    TaskStatus,
    GoalStatus,
)
from control_plane.store import FileStore


def _cp(tmp: Path) -> ControlPlane:
    return ControlPlane(store=FileStore(tmp / "state.json"))


def test_create_goal_and_budget(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal(
        title="Tiny CLI",
        description="Build a word-count CLI",
        acceptance_criteria=["has unit tests", "cli works"],
        budget_usd=5.0,
    )
    assert goal.status == GoalStatus.ACTIVE
    budget = cp.get_budget()
    assert budget.total_usd == 5.0
    assert budget.spent_usd == 0.0
    assert not budget.hard_stop


def test_propose_approve_accept_flow(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"], budget_usd=10.0)
    task = cp.propose_task(goal.id, "Write hello", "Implement hello world", estimated_cost_usd=0.5)
    assert task.status == TaskStatus.PROPOSED

    task = cp.approve_task(task.id)
    assert task.status == TaskStatus.APPROVED

    task = cp.mark_running(task.id)
    assert task.status == TaskStatus.RUNNING

    task = cp.submit_for_verification(task.id, artifact_path="./workspace/hello.py")
    assert task.status == TaskStatus.VERIFYING

    task = cp.accept_task(task.id, feedback="tests passed", cost_usd=0.4, cost_tokens=1200)
    assert task.status == TaskStatus.ACCEPTED
    assert cp.get_budget().spent_usd == 0.4


def test_budget_hard_stop(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"], budget_usd=1.0)
    task = cp.propose_task(goal.id, "Expensive", "costs a lot", estimated_cost_usd=2.0)
    try:
        cp.approve_task(task.id)
        assert False, "should have raised BudgetExceeded"
    except BudgetExceeded:
        pass
    task2 = cp.store.get_task(task.id)
    assert task2.status == TaskStatus.BLOCKED


def test_permission_hard_deny(tmp_path):
    cp = _cp(tmp_path)
    cp.create_goal("g", "d", ["ok"])
    try:
        cp.check_permission("git_push")
        assert False, "should deny git_push by default"
    except PermissionDenied:
        pass

    try:
        cp.check_permission("network")
        assert False, "should deny network by default"
    except PermissionDenied:
        pass

    # file_write inside allowed path is ok
    cp.check_permission("file_write", path="./workspace/foo.py")


def test_reject_and_replan(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"], budget_usd=10.0)
    task = cp.propose_task(goal.id, "t1", "desc")
    cp.approve_task(task.id)
    cp.mark_running(task.id)
    cp.submit_for_verification(task.id, "./out")
    task = cp.reject_task(task.id, feedback="tests failed: missing edge case")
    assert task.status == TaskStatus.REJECTED
    assert "edge case" in task.verifier_feedback


def test_checkpoint_created(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"])
    ckpts = cp.store.list_checkpoints(goal.id)
    assert len(ckpts) >= 1
    latest = cp.restore_from_latest(goal.id)
    assert latest is not None
    assert latest.goal_id == goal.id


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
