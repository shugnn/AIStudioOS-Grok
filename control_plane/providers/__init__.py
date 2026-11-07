"""Pluggable role backends. Product must not hard-depend on one LLM vendor."""

from __future__ import annotations

from typing import Any, Protocol


class ManagerBackend(Protocol):
    def propose_next_actions(self, goal_context: dict[str, Any]) -> list[dict[str, Any]]:
        """Return proposed tasks; Control Plane still approves."""


class WorkerBackend(Protocol):
    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute one approved task; return artifact paths + logs."""


class VerifierBackend(Protocol):
    def verify(self, task: dict[str, Any], worker_result: dict[str, Any]) -> dict[str, Any]:
        """Independent accept/reject."""


class NullManager:
    def propose_next_actions(self, goal_context: dict[str, Any]) -> list[dict[str, Any]]:
        return []


class ScriptWorker:
    """Placeholder: real script workers are invoked by L1 / exp runners today."""

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        return {"status": "skipped", "reason": "wire via existing script entrypoints"}


class ScriptVerifier:
    def verify(self, task: dict[str, Any], worker_result: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ACCEPTED" if worker_result.get("status") == "ok" else "REJECTED"}


def load_backends(kind: str) -> Any:
    """kind: manager|worker|verifier — default script/null."""
    if kind == "manager":
        return NullManager()
    if kind == "worker":
        return ScriptWorker()
    if kind == "verifier":
        return ScriptVerifier()
    raise ValueError(kind)
