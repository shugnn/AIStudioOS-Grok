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
    # Governance fields (ChatGPT review #7 / Grok #1)
    block_reason: Optional[str] = None
    blocked_by_policy: Optional[str] = None  # budget | permission | other
    unblock_approver: Optional[str] = None
    resume_status: Optional[str] = None      # status to restore after unblock
    retry_count: int = 0
    max_retries: int = 3
    reserved_usd: float = 0.0
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, goal_id: str, title: str, description: str, proposed_by: str = "manager",
               idempotency_key: Optional[str] = None, max_retries: int = 3, **meta) -> "Task":
        return cls(
            id=_new_id("task_"),
            goal_id=goal_id,
            title=title,
            description=description,
            proposed_by=proposed_by,
            idempotency_key=idempotency_key,
            max_retries=max_retries,
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
        # Backward compatible defaults for older state files
        d.setdefault("block_reason", None)
        d.setdefault("blocked_by_policy", None)
        d.setdefault("unblock_approver", None)
        d.setdefault("resume_status", None)
        d.setdefault("retry_count", 0)
        d.setdefault("max_retries", 3)
        d.setdefault("reserved_usd", 0.0)
        d.setdefault("idempotency_key", None)
        return cls(**d)


@dataclass
class Budget:
    """Hard budget envelope with reserve / settle lifecycle.

    Control Plane enforces it; Manager cannot override.
    Actual spend beyond total_usd requires human raise_budget (no auto-expand).
    """
    total_usd: float
    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    total_tokens: int = 0
    spent_tokens: int = 0
    hard_stop: bool = False
    last_updated: str = field(default_factory=_utcnow)

    def remaining_usd(self) -> float:
        return max(0.0, self.total_usd - self.spent_usd - self.reserved_usd)

    def can_spend(self, usd: float) -> bool:
        if self.hard_stop:
            return False
        return self.spent_usd + self.reserved_usd + usd <= self.total_usd

    def reserve(self, usd: float) -> None:
        if not self.can_spend(usd):
            raise ValueError("insufficient budget to reserve")
        self.reserved_usd += usd
        self.last_updated = _utcnow()

    def release(self, usd: float) -> None:
        self.reserved_usd = max(0.0, self.reserved_usd - usd)
        self.last_updated = _utcnow()

    def settle(self, reserved: float, actual: float, tokens: int = 0) -> None:
        """Convert reservation to actual spend; release unused reservation."""
        self.reserved_usd = max(0.0, self.reserved_usd - reserved)
        self.spent_usd += actual
        self.spent_tokens += tokens
        self.last_updated = _utcnow()
        if self.spent_usd + self.reserved_usd >= self.total_usd:
            self.hard_stop = True

    def record_spend(self, usd: float, tokens: int = 0) -> None:
        """Direct spend without prior reserve (legacy / simple path)."""
        self.spent_usd += usd
        self.spent_tokens += tokens
        self.last_updated = _utcnow()
        if self.spent_usd + self.reserved_usd >= self.total_usd:
            self.hard_stop = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Budget":
        d = dict(d)
        d.setdefault("reserved_usd", 0.0)
        return cls(**d)


@dataclass
class PermissionPolicy:
    """Hard permission rules. Prefer structured allow-lists over string deny-lists."""
    allow_file_write: bool = True
    allow_shell: bool = True
    allow_network: bool = False
    allow_git_push: bool = False
    allow_delete: bool = False
    allow_external_publish: bool = False
    max_file_size_mb: float = 10.0
    # Structured allow-lists (preferred)
    allowed_paths: list[str] = field(default_factory=lambda: ["./workspace", "./artifacts", "experiments/"])
    allowed_shell_commands: list[str] = field(default_factory=lambda: [
        "python", "python3", "pytest", "ls", "cat", "echo", "mkdir", "touch", "cp", "mv", "wc",
    ])
    # Secondary deny patterns (defense in depth, not sole control)
    denied_commands: list[str] = field(default_factory=lambda: ["rm -rf /", "sudo", "shutdown", "mkfs", ":(){"])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PermissionPolicy":
        d = dict(d)
        d.setdefault("allowed_shell_commands", [
            "python", "python3", "pytest", "ls", "cat", "echo", "mkdir", "touch", "cp", "mv", "wc",
        ])
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
