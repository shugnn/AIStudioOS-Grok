"""Core data models for AIStudioOS Control Plane.

These models are intentionally simple and serializable so the first
experiment can run with a file / SQLite backend. Later they can be
mapped to Postgres without changing the public interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class TaskStatus(str, Enum):
    PROPOSED = "proposed"          # Manager proposed, not yet approved by Control Plane
    APPROVED = "approved"          # Ready for Worker
    RUNNING = "running"
    VERIFYING = "verifying"
    ACCEPTED = "accepted"          # Independent Verifier passed
    REJECTED = "rejected"          # Verifier failed; needs re-plan
    BLOCKED = "blocked"            # Waiting for human (budget / permission)
    CANCELLED = "cancelled"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


@dataclass
class Goal:
    id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    status: GoalStatus = GoalStatus.ACTIVE
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, title: str, description: str, acceptance_criteria: list[str], **meta) -> "Goal":
        return cls(
            id=_new_id("goal_"),
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria,
            metadata=meta,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Goal":
        d = dict(d)
        d["status"] = GoalStatus(d["status"])
        return cls(**d)


@dataclass
class Task:
    id: str
    goal_id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PROPOSED
    proposed_by: str = "manager"
    artifact_path: Optional[str] = None
    verifier_feedback: Optional[str] = None
    cost_tokens: int = 0
    cost_usd: float = 0.0
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, goal_id: str, title: str, description: str, proposed_by: str = "manager", **meta) -> "Task":
        return cls(
            id=_new_id("task_"),
            goal_id=goal_id,
            title=title,
            description=description,
            proposed_by=proposed_by,
            metadata=meta,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        d = dict(d)
        d["status"] = TaskStatus(d["status"])
        return cls(**d)


@dataclass
class Budget:
    """Hard budget envelope. Control Plane enforces it; Manager cannot override."""
    total_usd: float
    spent_usd: float = 0.0
    total_tokens: int = 0
    spent_tokens: int = 0
    hard_stop: bool = False          # True => no more spend allowed until human raises limit
    last_updated: str = field(default_factory=_utcnow)

    def remaining_usd(self) -> float:
        return max(0.0, self.total_usd - self.spent_usd)

    def can_spend(self, usd: float) -> bool:
        if self.hard_stop:
            return False
        return self.spent_usd + usd <= self.total_usd

    def record_spend(self, usd: float, tokens: int = 0) -> None:
        self.spent_usd += usd
        self.spent_tokens += tokens
        self.last_updated = _utcnow()
        if self.spent_usd >= self.total_usd:
            self.hard_stop = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Budget":
        return cls(**d)


@dataclass
class PermissionPolicy:
    """Hard permission rules. Checked before any Worker action that has side effects."""
    allow_file_write: bool = True
    allow_shell: bool = True
    allow_network: bool = False
    allow_git_push: bool = False
    allow_delete: bool = False
    allow_external_publish: bool = False
    max_file_size_mb: float = 10.0
    allowed_paths: list[str] = field(default_factory=lambda: ["./workspace", "./artifacts"])
    denied_commands: list[str] = field(default_factory=lambda: ["rm -rf /", "sudo", "shutdown"])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PermissionPolicy":
        return cls(**d)


@dataclass
class Checkpoint:
    id: str
    goal_id: str
    label: str
    state_snapshot: dict[str, Any]
    created_at: str = field(default_factory=_utcnow)

    @classmethod
    def create(cls, goal_id: str, label: str, state_snapshot: dict) -> "Checkpoint":
        return cls(
            id=_new_id("ckpt_"),
            goal_id=goal_id,
            label=label,
            state_snapshot=state_snapshot,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Checkpoint":
        return cls(**d)
