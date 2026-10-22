"""Thin Control Plane for AIStudioOS-Grok Phase 1.

Design rules (non-negotiable for the minimal experiment):
- Manager only *proposes*. Control Plane decides approval / rejection / block.
- Budget and permissions are hard-enforced here, not by prompt.
- Every state change is durable (via FileStore).
- Independent Verifier result is the only path to ACCEPTED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .models import (
    Budget,
    Checkpoint,
    Goal,
    GoalStatus,
    PermissionPolicy,
    Task,
    TaskStatus,
)
from .store import FileStore


class ControlPlaneError(Exception):
    pass


class BudgetExceeded(ControlPlaneError):
    pass


class PermissionDenied(ControlPlaneError):
    pass


class ControlPlane:
    def __init__(self, store: Optional[FileStore] = None):
        self.store = store or FileStore()

    # ------------------------------------------------------------------
    # Goal lifecycle
    # ------------------------------------------------------------------
    def create_goal(
        self,
        title: str,
        description: str,
        acceptance_criteria: list[str],
        budget_usd: float = 20.0,
        **meta,
    ) -> Goal:
        goal = Goal.create(title, description, acceptance_criteria, **meta)
        self.store.save_goal(goal)

        # Reset / set budget envelope for this experiment
        budget = Budget(total_usd=budget_usd)
        self.store.save_budget(budget)

        self._checkpoint(goal.id, "goal_created", {"goal": goal.to_dict()})
        return goal

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self.store.get_goal(goal_id)

    def complete_goal(self, goal_id: str) -> Goal:
        goal = self._require_goal(goal_id)
        goal.status = GoalStatus.COMPLETED
        goal.updated_at = _now()
        self.store.save_goal(goal)
        self._checkpoint(goal_id, "goal_completed", {"goal": goal.to_dict()})
        return goal

    # ------------------------------------------------------------------
    # Task proposal → approval (Manager proposes, CP decides)
    # ------------------------------------------------------------------
    def propose_task(
        self,
        goal_id: str,
        title: str,
        description: str,
        proposed_by: str = "manager",
        estimated_cost_usd: float = 0.0,
        **meta,
    ) -> Task:
        """Manager calls this. Control Plane may auto-approve or leave as PROPOSED."""
        self._require_goal(goal_id)
        task = Task.create(goal_id, title, description, proposed_by=proposed_by, **meta)
        task.metadata["estimated_cost_usd"] = estimated_cost_usd
        self.store.save_task(task)
        return task

    def approve_task(self, task_id: str) -> Task:
        task = self._require_task(task_id)
        if task.status not in (TaskStatus.PROPOSED, TaskStatus.REJECTED):
            raise ControlPlaneError(f"Cannot approve task in status {task.status}")

        budget = self.store.get_budget()
        est = float(task.metadata.get("estimated_cost_usd", 0.0))
        if not budget.can_spend(est):
            task.status = TaskStatus.BLOCKED
            task.updated_at = _now()
            self.store.save_task(task)
            raise BudgetExceeded(
                f"Budget remaining ${budget.remaining_usd():.2f}, "
                f"estimated need ${est:.2f}. Task blocked pending human approval."
            )

        task.status = TaskStatus.APPROVED
        task.updated_at = _now()
        self.store.save_task(task)
        self._checkpoint(task.goal_id, f"task_approved_{task.id}", {"task": task.to_dict()})
        return task

    def mark_running(self, task_id: str) -> Task:
        task = self._require_task(task_id)
        if task.status != TaskStatus.APPROVED:
            raise ControlPlaneError(f"Task must be APPROVED to run, got {task.status}")
        task.status = TaskStatus.RUNNING
        task.updated_at = _now()
        self.store.save_task(task)
        return task

    def submit_for_verification(self, task_id: str, artifact_path: str) -> Task:
        task = self._require_task(task_id)
        if task.status != TaskStatus.RUNNING:
            raise ControlPlaneError(f"Task must be RUNNING to submit, got {task.status}")
        task.status = TaskStatus.VERIFYING
        task.artifact_path = artifact_path
        task.updated_at = _now()
        self.store.save_task(task)
        return task

    def accept_task(
        self,
        task_id: str,
        feedback: str = "accepted",
        cost_usd: float = 0.0,
        cost_tokens: int = 0,
    ) -> Task:
        """Called only by Independent Verifier (or human)."""
        task = self._require_task(task_id)
        if task.status != TaskStatus.VERIFYING:
            raise ControlPlaneError(f"Task must be VERIFYING to accept, got {task.status}")

        # Hard budget enforcement at acceptance time as well
        budget = self.store.get_budget()
        if cost_usd > 0 and not budget.can_spend(cost_usd):
            task.status = TaskStatus.BLOCKED
            task.verifier_feedback = "Budget exceeded at acceptance"
            task.updated_at = _now()
            self.store.save_task(task)
            raise BudgetExceeded("Cannot accept: budget would be exceeded")

        if cost_usd > 0:
            budget.record_spend(cost_usd, cost_tokens)
            self.store.save_budget(budget)

        task.status = TaskStatus.ACCEPTED
        task.verifier_feedback = feedback
        task.cost_usd = cost_usd
        task.cost_tokens = cost_tokens
        task.updated_at = _now()
        self.store.save_task(task)
        self._checkpoint(task.goal_id, f"task_accepted_{task.id}", {"task": task.to_dict()})
        return task

    def reject_task(self, task_id: str, feedback: str) -> Task:
        task = self._require_task(task_id)
        if task.status != TaskStatus.VERIFYING:
            raise ControlPlaneError(f"Task must be VERIFYING to reject, got {task.status}")
        task.status = TaskStatus.REJECTED
        task.verifier_feedback = feedback
        task.updated_at = _now()
        self.store.save_task(task)
        self._checkpoint(task.goal_id, f"task_rejected_{task.id}", {"task": task.to_dict()})
        return task

    # ------------------------------------------------------------------
    # Permission checks (hard)
    # ------------------------------------------------------------------
    def check_permission(self, action: str, **kwargs) -> None:
        """Raise PermissionDenied if the action is not allowed by hard policy."""
        policy = self.store.get_policy()

        if action == "file_write":
            if not policy.allow_file_write:
                raise PermissionDenied("file_write is disabled by policy")
            path = kwargs.get("path", "")
            if policy.allowed_paths and not any(path.startswith(p) for p in policy.allowed_paths):
                raise PermissionDenied(f"Path '{path}' not in allowed_paths")

        elif action == "shell":
            if not policy.allow_shell:
                raise PermissionDenied("shell is disabled by policy")
            cmd = kwargs.get("command", "")
            for denied in policy.denied_commands:
                if denied in cmd:
                    raise PermissionDenied(f"Command contains denied pattern: {denied}")

        elif action == "network":
            if not policy.allow_network:
                raise PermissionDenied("network is disabled by policy")

        elif action == "git_push":
            if not policy.allow_git_push:
                raise PermissionDenied("git_push is disabled by policy")

        elif action == "delete":
            if not policy.allow_delete:
                raise PermissionDenied("delete is disabled by policy")

        elif action == "external_publish":
            if not policy.allow_external_publish:
                raise PermissionDenied("external_publish is disabled by policy")

        else:
            raise PermissionDenied(f"Unknown action: {action}")

    def update_policy(self, **kwargs) -> PermissionPolicy:
        """Human-only operation to change hard policy."""
        policy = self.store.get_policy()
        for k, v in kwargs.items():
            if hasattr(policy, k):
                setattr(policy, k, v)
        self.store.save_policy(policy)
        return policy

    # ------------------------------------------------------------------
    # Budget human operations
    # ------------------------------------------------------------------
    def raise_budget(self, additional_usd: float) -> Budget:
        """Human raises the budget ceiling and clears hard_stop."""
        budget = self.store.get_budget()
        budget.total_usd += additional_usd
        budget.hard_stop = False
        budget.last_updated = _now()
        self.store.save_budget(budget)
        return budget

    def get_budget(self) -> Budget:
        return self.store.get_budget()

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------
    def create_checkpoint(self, goal_id: str, label: str) -> Checkpoint:
        snapshot = self.store.snapshot()
        ckpt = Checkpoint.create(goal_id, label, snapshot)
        self.store.save_checkpoint(ckpt)
        return ckpt

    def restore_from_latest(self, goal_id: str) -> Optional[Checkpoint]:
        """Return the latest checkpoint (caller can re-hydrate workers from it)."""
        return self.store.latest_checkpoint(goal_id)

    def list_tasks(self, goal_id: str, status: Optional[TaskStatus] = None) -> list[Task]:
        return self.store.list_tasks(goal_id=goal_id, status=status)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _require_goal(self, goal_id: str) -> Goal:
        goal = self.store.get_goal(goal_id)
        if not goal:
            raise ControlPlaneError(f"Goal not found: {goal_id}")
        return goal

    def _require_task(self, task_id: str) -> Task:
        task = self.store.get_task(task_id)
        if not task:
            raise ControlPlaneError(f"Task not found: {task_id}")
        return task

    def _checkpoint(self, goal_id: str, label: str, extra: dict) -> None:
        snapshot = self.store.snapshot()
        snapshot["_extra"] = extra
        ckpt = Checkpoint.create(goal_id, label, snapshot)
        self.store.save_checkpoint(ckpt)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
