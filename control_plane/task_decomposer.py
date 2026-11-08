"""Minimal task decomposer skeleton.

L2 (self-task + implement) is NOT started.
This is a placeholder interface only — no real decomposition logic,
no LLM calls, no business claim. Scaffold policy applies.
"""

from __future__ import annotations

from typing import Any


class TaskDecomposer:
    """Protocol-like skeleton for future goal → subtasks split."""

    def decompose(self, goal: dict[str, Any]) -> list[dict[str, Any]]:
        """Return proposed subtasks. Currently always empty."""
        return []


def get_decomposer() -> TaskDecomposer:
    return TaskDecomposer()
