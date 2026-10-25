"""Simple durable store for the first experiment.

Uses a single JSON file on disk so we have zero external dependencies
for Phase 1. Can be replaced by SQLite / Postgres later without changing
the ControlPlane public API.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from .models import (
    Budget,
    Checkpoint,
    Goal,
    GoalStatus,
    PermissionPolicy,
    Task,
    TaskStatus,
)


class FileStore:
    """Thread-safe JSON file store for Control Plane state."""

    def __init__(self, path: str | Path = "control_plane/state.json"):
        self.path = Path(path)
        self.bak_path = self.path.with_suffix(".bak")
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({
                "goals": {},
                "tasks": {},
                "budget": Budget(total_usd=20.0).to_dict(),
                "policy": PermissionPolicy().to_dict(),
                "checkpoints": {},
                "meta": {"version": 1},
            })
        else:
            self._read()  # corruption detection on startup

    def _read(self) -> dict:
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                if self.bak_path.exists():
                    with open(self.bak_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._write(data)
                    return data
                raise RuntimeError(
                    f"State file corrupt and no usable backup: {self.path} ({e})"
                ) from e

    def _write(self, data: dict) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path)
            try:
                import shutil
                shutil.copy2(self.path, self.bak_path)
            except OSError:
                pass

    # ---- Goal ----
    def save_goal(self, goal: Goal) -> None:
        data = self._read()
        data["goals"][goal.id] = goal.to_dict()
        self._write(data)

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        data = self._read()
        raw = data["goals"].get(goal_id)
        return Goal.from_dict(raw) if raw else None

    def list_goals(self, status: Optional[GoalStatus] = None) -> list[Goal]:
        data = self._read()
        goals = [Goal.from_dict(g) for g in data["goals"].values()]
        if status:
            goals = [g for g in goals if g.status == status]
        return goals

    # ---- Task ----
    def save_task(self, task: Task) -> None:
        data = self._read()
        data["tasks"][task.id] = task.to_dict()
        self._write(data)

    def get_task(self, task_id: str) -> Optional[Task]:
        data = self._read()
        raw = data["tasks"].get(task_id)
        return Task.from_dict(raw) if raw else None

    def list_tasks(self, goal_id: Optional[str] = None, status: Optional[TaskStatus] = None) -> list[Task]:
        data = self._read()
        tasks = [Task.from_dict(t) for t in data["tasks"].values()]
        if goal_id:
            tasks = [t for t in tasks if t.goal_id == goal_id]
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    # ---- Budget ----
    def get_budget(self) -> Budget:
        data = self._read()
        return Budget.from_dict(data["budget"])

    def save_budget(self, budget: Budget) -> None:
        data = self._read()
        data["budget"] = budget.to_dict()
        self._write(data)

    # ---- Policy ----
    def get_policy(self) -> PermissionPolicy:
        data = self._read()
        return PermissionPolicy.from_dict(data["policy"])

    def save_policy(self, policy: PermissionPolicy) -> None:
        data = self._read()
        data["policy"] = policy.to_dict()
        self._write(data)

    # ---- Checkpoint ----
    def save_checkpoint(self, ckpt: Checkpoint, keep_last: int = 30) -> None:
        data = self._read()
        data["checkpoints"][ckpt.id] = ckpt.to_dict()
        # Cap growth: keep only the newest keep_last checkpoints globally
        items = sorted(
            data["checkpoints"].items(),
            key=lambda kv: kv[1].get("created_at", ""),
        )
        if len(items) > keep_last:
            data["checkpoints"] = dict(items[-keep_last:])
        self._write(data)

    def get_checkpoint(self, ckpt_id: str) -> Optional[Checkpoint]:
        data = self._read()
        raw = data["checkpoints"].get(ckpt_id)
        return Checkpoint.from_dict(raw) if raw else None

    def list_checkpoints(self, goal_id: Optional[str] = None) -> list[Checkpoint]:
        data = self._read()
        ckpts = [Checkpoint.from_dict(c) for c in data["checkpoints"].values()]
        if goal_id:
            ckpts = [c for c in ckpts if c.goal_id == goal_id]
        return sorted(ckpts, key=lambda c: c.created_at)

    def latest_checkpoint(self, goal_id: str) -> Optional[Checkpoint]:
        ckpts = self.list_checkpoints(goal_id)
        return ckpts[-1] if ckpts else None

    def snapshot(self) -> dict[str, Any]:
        """Full state for recovery."""
        return self._read()
