#!/usr/bin/env python3
"""Exp-02: continuous auto-execution closed loop (no LLM, $0).

Goal: prove automatic observe→claim→execute→verify→next without human
between tasks, until queue empty or max_steps.

Roles (scripted):
  Manager  — picks next PROPOSED/queued task
  Worker   — runs deterministic job
  Verifier — checks output invariants independently
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "progress" / "exp02_auto_loop"
OUT.mkdir(parents=True, exist_ok=True)


@dataclass
class Task:
    id: str
    kind: str
    payload: dict
    status: str = "queued"  # queued|running|verified|failed
    result: dict = field(default_factory=dict)
    verify: dict = field(default_factory=dict)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def worker_word_count(text: str) -> dict:
    words = [w for w in text.split() if w]
    return {"word_count": len(words), "text": text}


def worker_checksum(n: int) -> dict:
    s = sum(range(n + 1))
    return {"n": n, "sum_0_to_n": s}


def verifier(task: Task) -> dict:
    r = task.result
    if task.kind == "word_count":
        expected = len([w for w in task.payload.get("text", "").split() if w])
        ok = r.get("word_count") == expected
        return {"ok": ok, "expected": expected, "got": r.get("word_count")}
    if task.kind == "checksum":
        n = int(task.payload.get("n", 0))
        expected = n * (n + 1) // 2
        ok = r.get("sum_0_to_n") == expected
        return {"ok": ok, "expected": expected, "got": r.get("sum_0_to_n")}
    return {"ok": False, "error": "unknown_kind"}


def execute(task: Task) -> dict:
    if task.kind == "word_count":
        return worker_word_count(task.payload.get("text", ""))
    if task.kind == "checksum":
        return worker_checksum(int(task.payload.get("n", 0)))
    return {"error": "unknown_kind"}


def seed_queue() -> list[Task]:
    return [
        Task(id="t1", kind="word_count", payload={"text": "auto loop proves closed execution"}),
        Task(id="t2", kind="checksum", payload={"n": 100}),
        Task(id="t3", kind="word_count", payload={"text": "manager worker verifier"}),
        Task(id="t4", kind="checksum", payload={"n": 10}),
    ]


def run_loop(max_steps: int = 20) -> dict:
    queue = seed_queue()
    log: list[dict] = []
    steps = 0
    human_interventions = 0
    budget_usd = 0.0

    while steps < max_steps:
        # Manager: select next queued
        pending = [t for t in queue if t.status == "queued"]
        if not pending:
            break
        task = pending[0]
        task.status = "running"
        steps += 1
        # Worker
        task.result = execute(task)
        # Verifier (independent of worker path — recomputes expected)
        task.verify = verifier(task)
        task.status = "verified" if task.verify.get("ok") else "failed"
        entry = {
            "step": steps,
            "utc": utc(),
            "task_id": task.id,
            "kind": task.kind,
            "status": task.status,
            "verify": task.verify,
        }
        log.append(entry)
        if task.status == "failed":
            # auto-stop on failure (safe default); no human in loop
            break

    report = {
        "experiment": "exp02_auto_loop",
        "utc": utc(),
        "steps": steps,
        "completed": sum(1 for t in queue if t.status == "verified"),
        "failed": sum(1 for t in queue if t.status == "failed"),
        "queued_remaining": sum(1 for t in queue if t.status == "queued"),
        "human_interventions": human_interventions,
        "budget_usd": budget_usd,
        "closed_loop": True,
        "llm_used": False,
        "log": log,
        "tasks": [
            {
                "id": t.id,
                "kind": t.kind,
                "status": t.status,
                "verify": t.verify,
            }
            for t in queue
        ],
    }
    path = OUT / f"exp02-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact"] = str(path)
    return report


def main() -> int:
    r = run_loop()
    print(json.dumps({k: r[k] for k in r if k != "log"}, indent=2))
    print("log_steps:", len(r["log"]))
    ok = r["failed"] == 0 and r["completed"] >= 4 and r["human_interventions"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
