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


def test_budget_reserve_and_settle(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"], budget_usd=5.0)
    task = cp.propose_task(goal.id, "t", "d", estimated_cost_usd=1.0)
    task = cp.approve_task(task.id)
    assert task.reserved_usd == 1.0
    assert cp.get_budget().reserved_usd == 1.0
    cp.mark_running(task.id)
    cp.submit_for_verification(task.id, "./out")
    task = cp.accept_task(task.id, cost_usd=0.6, cost_tokens=100)
    assert task.status == TaskStatus.ACCEPTED
    b = cp.get_budget()
    assert abs(b.spent_usd - 0.6) < 1e-9
    assert abs(b.reserved_usd) < 1e-9


def test_reject_releases_reservation_and_retry_limit(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"], budget_usd=10.0)
    task = cp.propose_task(goal.id, "t", "d", estimated_cost_usd=1.0)
    # force low max_retries via metadata path — set after create
    task.max_retries = 1
    cp.store.save_task(task)
    cp.approve_task(task.id)
    cp.mark_running(task.id)
    cp.submit_for_verification(task.id, "./out")
    task = cp.reject_task(task.id, "fail1")
    assert task.status == TaskStatus.REJECTED
    assert task.retry_count == 1
    assert abs(cp.get_budget().reserved_usd) < 1e-9
    # re-approve and reject again -> cancel
    cp.approve_task(task.id)
    cp.mark_running(task.id)
    cp.submit_for_verification(task.id, "./out")
    task = cp.reject_task(task.id, "fail2")
    assert task.status == TaskStatus.CANCELLED
    assert task.retry_count == 2


def test_unblock_requires_human(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"], budget_usd=0.5)
    task = cp.propose_task(goal.id, "t", "d", estimated_cost_usd=2.0)
    try:
        cp.approve_task(task.id)
    except BudgetExceeded:
        pass
    task = cp.store.get_task(task.id)
    assert task.status == TaskStatus.BLOCKED
    assert task.blocked_by_policy == "budget"
    assert task.block_reason
    task = cp.unblock_task(task.id, approver="founder")
    assert task.status == TaskStatus.PROPOSED
    assert task.unblock_approver == "founder"


def test_shell_allowlist(tmp_path):
    cp = _cp(tmp_path)
    cp.create_goal("g", "d", ["ok"])
    cp.check_permission("shell", command="pytest -q")
    try:
        cp.check_permission("shell", command="curl http://evil")
        assert False
    except PermissionDenied:
        pass


def test_idempotency_key_dedup(tmp_path):
    cp = _cp(tmp_path)
    goal = cp.create_goal("g", "d", ["ok"])
    t1 = cp.propose_task(goal.id, "t", "d", idempotency_key="k1")
    t2 = cp.propose_task(goal.id, "t again", "d", idempotency_key="k1")
    assert t1.id == t2.id


def test_corrupt_state_recovers_from_bak(tmp_path):
    store_path = tmp_path / "state.json"
    cp = ControlPlane(store=FileStore(store_path))
    goal = cp.create_goal("g", "d", ["ok"])
    # corrupt primary
    store_path.write_text("{not json")
    cp2 = ControlPlane(store=FileStore(store_path))
    g = cp2.get_goal(goal.id)
    assert g is not None
    assert g.title == "g"
