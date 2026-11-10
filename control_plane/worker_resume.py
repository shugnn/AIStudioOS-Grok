"""Durable job resume for the product Worker entry.

`scripts/worker_run_task.py` calls `run_resumable` when a task module exposes
`JOB_SPECS` and `execute_job`. Each committed job is fsync'd into
`task_inbox/<id>/state/checkpoint.json` before the next job starts. A one-shot
inject token `inject/sigkill_at` can arm an external SIGKILL at a named
boundary. The killed process does not catch SIGKILL. The next invocation of
the same entry reads the checkpoint, skips jobs whose artifacts still match,
and finishes the rest.

This module does not start a soak, does not register schedulers, and is not
a production 7×24 claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

FROZEN_ORDERS_SHA = "633aded091b1da111f4c3c9c378c975d3bdddf17e85a0fd3b001c7e4ddbf7ffe"
FROZEN_ORDERS_BYTES = 237705
FROZEN_ORDERS_LINES = 6001
SEALED_TASK_ID = "DS-T1-20261108"
RECOVERY_KEYS = (
    "task_id",
    "killed_pid",
    "kill_checkpoint",
    "killed_utc",
    "resumed_utc",
    "jobs_done_before",
    "jobs_done_after",
    "duplicate_jobs",
    "idempotency_keys",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("utc must be a string")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def utc_strictly_after(previous: str) -> str:
    prev = parse_utc(previous)
    while True:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if now > prev:
            return now.strftime("%Y-%m-%dT%H:%M:%SZ")
        time.sleep(0.05)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def dumps(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    dirfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _resolve(inbox: Path, rel: str) -> Path:
    parts = Path(rel).parts
    if not rel or rel.startswith("/") or ".." in parts:
        raise ValueError(f"artifact path escapes inbox: {rel}")
    path = (inbox / rel).resolve()
    inbox_root = inbox.resolve()
    if path != inbox_root and inbox_root not in path.parents:
        raise ValueError(f"artifact path escapes inbox: {rel}")
    return path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cmdline() -> str:
    raw = Path("/proc/self/cmdline").read_bytes()
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _empty_checkpoint(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "jobs": {},
        "journal": [],
        "duplicate_jobs": [],
        "started_utc": utc_now(),
    }


def _load_checkpoint(path: Path, task_id: str) -> tuple[dict | None, str | None]:
    if not path.exists():
        return _empty_checkpoint(task_id), None
    try:
        ckpt = _load_json(path)
    except json.JSONDecodeError:
        return None, "CHECKPOINT_UNREADABLE"
    if not isinstance(ckpt, dict) or ckpt.get("task_id") != task_id:
        return None, "TASK_ID_MISMATCH"
    ckpt.setdefault("jobs", {})
    ckpt.setdefault("journal", [])
    ckpt.setdefault("duplicate_jobs", [])
    return ckpt, None


def _append(ckpt: dict, event: dict) -> None:
    row = dict(event)
    row["seq"] = len(ckpt["journal"]) + 1
    ckpt["journal"].append(row)


def _save_checkpoint(path: Path, ckpt: dict) -> None:
    atomic_write_bytes(path, dumps(ckpt))


def _already_committed(ckpt: dict, job_id: str) -> bool:
    return any(
        event.get("event") == "job_committed" and event.get("job_id") == job_id
        for event in ckpt["journal"]
    )


def _hash_rel(inbox: Path, rel: str) -> dict:
    path = _resolve(inbox, rel)
    raw = path.read_bytes()
    return {"rel": rel, "sha256": sha256_bytes(raw), "bytes": len(raw)}


def _artifacts_match(inbox: Path, record: dict) -> bool:
    artifacts = record.get("artifacts") or []
    if not artifacts:
        return False
    for item in artifacts:
        try:
            current = _hash_rel(inbox, item["rel"])
        except (OSError, ValueError):
            return False
        if current["sha256"] != item.get("sha256"):
            return False
    return True


def _reusable(inbox: Path, ckpt: dict, job_id: str) -> bool:
    record = ckpt["jobs"].get(job_id)
    return bool(record and record.get("status") == "DONE" and _artifacts_match(inbox, record))


def _job_key(task_id: str, job_id: str) -> str:
    return f"{task_id}:{job_id}"


def _evidence(task_id: str, record: dict) -> dict:
    def one(item: dict) -> dict:
        body = {"path": f"task_inbox/{task_id}/{item['rel']}", "sha256": item["sha256"]}
        fingerprint = record.get("fingerprint")
        if item["rel"].endswith("orders.csv") and isinstance(fingerprint, dict):
            body["bytes"] = fingerprint.get("bytes")
            body["lines"] = fingerprint.get("lines")
        return body

    artifacts = record["artifacts"]
    if len(artifacts) == 1:
        return one(artifacts[0])
    return {"paths": [one(item) for item in artifacts]}


def _sync_dispatch(
    inbox: Path,
    ckpt: dict,
    specs: list[dict],
    *,
    fingerprint_match: bool | None,
    final: bool,
    executed_utc: str | None = None,
) -> None:
    path = inbox / "dispatch.json"
    if path.exists():
        document = _load_json(path)
    else:
        document = {"task_id": ckpt["task_id"], "jobs": []}
    by_id = {job["job_id"]: job for job in document.get("jobs", []) if isinstance(job, dict)}
    ordered = []
    for spec in specs:
        row = dict(by_id.get(spec["job_id"], {}))
        row["job_id"] = spec["job_id"]
        row["title"] = spec["title"]
        record = ckpt["jobs"].get(spec["job_id"])
        if record and record.get("status") == "DONE":
            row["status"] = "DONE"
            row["evidence"] = _evidence(ckpt["task_id"], record)
        else:
            row["status"] = "PENDING"
            row.pop("evidence", None)
        ordered.append(row)
    document["task_id"] = ckpt["task_id"]
    document["jobs"] = ordered
    document["network"] = False
    document["paid"] = False
    document["worker"] = "scripts/worker_run_task.py"
    if fingerprint_match is not None:
        document["fingerprint_match"] = fingerprint_match
    if final:
        document["executed_utc"] = executed_utc or utc_now()
        document["executed_by"] = "scripts/worker_run_task.py"
    else:
        # A kill between jobs must not inherit a previous run's completion stamp.
        document.pop("executed_utc", None)
        document.pop("executed_by", None)
    atomic_write_bytes(path, dumps(document))


def _mark_job_failed(inbox: Path, job_id: str, reason: str) -> None:
    path = inbox / "dispatch.json"
    if not path.exists():
        return
    document = _load_json(path)
    for row in document.get("jobs", []):
        if row.get("job_id") == job_id:
            row["status"] = "FAILED"
            row["detail"] = reason
            row.pop("evidence", None)
    atomic_write_bytes(path, dumps(document))


def _fingerprint_match(ckpt: dict) -> bool:
    fingerprint = ckpt.get("jobs", {}).get("J1", {}).get("fingerprint")
    return bool(isinstance(fingerprint, dict) and fingerprint.get("match_expected"))


def _result(ckpt: dict, *, status: str, ok: bool, deliverables: str | None = None) -> dict:
    fingerprint = ckpt.get("jobs", {}).get("J1", {}).get("fingerprint") or {}
    window = ckpt.get("kill_window") or {}
    sigkill = ckpt.get("sigkill") or {}
    resume = ckpt.get("resume") or {}
    return {
        "ok": ok,
        "status": status,
        "fingerprint_match": bool(fingerprint.get("match_expected")),
        "sha256_orders": fingerprint.get("sha256"),
        "bytes": fingerprint.get("bytes"),
        "lines": fingerprint.get("lines"),
        "duplicate_jobs": list(ckpt.get("duplicate_jobs") or []),
        "killed_pid": sigkill.get("killed_pid"),
        "kill_checkpoint": window.get("kill_checkpoint"),
        "killed_utc": sigkill.get("killed_utc"),
        "resumed_utc": resume.get("resumed_utc"),
        "jobs_done_before": list(window.get("jobs_done") or []),
        "deliverables": deliverables,
        "network": False,
        "paid": False,
        "recovery": status == "DONE",
    }


def _done_ids(ckpt: dict, specs: list[dict]) -> list[str]:
    return [
        spec["job_id"]
        for spec in specs
        if ckpt["jobs"].get(spec["job_id"], {}).get("status") == "DONE"
    ]


def _arm_and_block(
    *,
    inbox: Path,
    ckpt: dict,
    ckpt_path: Path,
    specs: list[dict],
    boundary: str,
    token_path: Path,
) -> NoReturn:
    done = _done_ids(ckpt, specs)
    not_started = [spec["job_id"] for spec in specs if spec["job_id"] not in done]
    ready_utc = utc_now()
    pid = os.getpid()
    window = {
        "pid": pid,
        "kill_checkpoint": boundary,
        "ready_utc": ready_utc,
        "jobs_done": done,
        "jobs_not_started": not_started,
        "task_id": ckpt["task_id"],
        "cmdline": _cmdline(),
        "inject_consumed": True,
    }
    ckpt["kill_window"] = window
    _append(
        ckpt,
        {
            "event": "kill_window_open",
            "kill_checkpoint": boundary,
            "pid": pid,
            "jobs_done": list(done),
            "utc": ready_utc,
        },
    )
    _save_checkpoint(ckpt_path, ckpt)
    _sync_dispatch(
        inbox,
        ckpt,
        specs,
        fingerprint_match=_fingerprint_match(ckpt),
        final=False,
    )
    dispatch_bytes = (inbox / "dispatch.json").read_bytes()
    atomic_write_bytes(inbox / "state" / "kill_window.json", dumps(window))
    atomic_write_bytes(inbox / "state" / "dispatch_at_kill.json", dispatch_bytes)
    token_path.unlink()
    _fsync_dir(token_path.parent)
    _fsync_dir(inbox / "state")
    while True:
        time.sleep(0.2)


def _read_sigkill_event(path: Path, window: dict) -> tuple[dict | None, str | None]:
    if not path.is_file():
        return None, "SIGKILL_EVENT_MISSING"
    try:
        data = _load_json(path)
        pid = int(data["killed_pid"])
        signal_no = int(data["signal"])
        killed_utc = data["killed_utc"]
        checkpoint = data["kill_checkpoint"]
        parse_utc(killed_utc)
        ready = parse_utc(window["ready_utc"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, "SIGKILL_EVENT_INVALID"
    if pid <= 0 or pid != int(window["pid"]):
        return None, "KILLED_PID_MISMATCH"
    if pid == os.getpid():
        return None, "KILLED_PID_IS_CURRENT"
    if signal_no != 9:
        return None, "SIGNAL_NOT_SIGKILL"
    if checkpoint != window.get("kill_checkpoint"):
        return None, "KILL_CHECKPOINT_MISMATCH"
    if parse_utc(killed_utc) < ready:
        return None, "KILLED_BEFORE_READY"
    return data, None


def _commit_job(
    *,
    inbox: Path,
    ckpt: dict,
    ckpt_path: Path,
    specs: list[dict],
    spec: dict,
    artifacts: list[dict],
    extra: dict,
    final: bool,
) -> None:
    job_id = spec["job_id"]
    record = {
        "status": "DONE",
        "title": spec["title"],
        "idempotency_key": _job_key(ckpt["task_id"], job_id),
        "completed_utc": utc_now(),
        "artifacts": artifacts,
    }
    if "fingerprint" in extra:
        record["fingerprint"] = extra["fingerprint"]
    ckpt["jobs"][job_id] = record
    _append(
        ckpt,
        {
            "event": "job_committed",
            "job_id": job_id,
            "idempotency_key": record["idempotency_key"],
            "utc": record["completed_utc"],
        },
    )
    _save_checkpoint(ckpt_path, ckpt)
    _sync_dispatch(
        inbox,
        ckpt,
        specs,
        fingerprint_match=_fingerprint_match(ckpt),
        final=final,
        executed_utc=record["completed_utc"] if final else None,
    )


def _write_recovery_and_manifest(
    *,
    module: Any,
    inbox: Path,
    out: Path,
    ckpt: dict,
    specs: list[dict],
) -> list[str]:
    """Write recovery_report.json from the checkpoint, then manifest.json."""
    task_id = ckpt["task_id"]
    window = ckpt["kill_window"]
    report = {
        "task_id": task_id,
        "killed_pid": int(ckpt["sigkill"]["killed_pid"]),
        "kill_checkpoint": window["kill_checkpoint"],
        "killed_utc": ckpt["sigkill"]["killed_utc"],
        "resumed_utc": ckpt["resume"]["resumed_utc"],
        "jobs_done_before": list(window["jobs_done"]),
        "jobs_done_after": [spec["job_id"] for spec in specs],
        "duplicate_jobs": list(ckpt.get("duplicate_jobs") or []),
        "idempotency_keys": [],
    }
    # Collisions only. An empty list means each committed key was used once.
    seen: dict[str, int] = {}
    for event in ckpt["journal"]:
        if event.get("event") != "job_committed":
            continue
        key = event.get("idempotency_key")
        if not isinstance(key, str):
            continue
        seen[key] = seen.get(key, 0) + 1
    report["idempotency_keys"] = [key for key, count in seen.items() if count > 1]
    recovery_rel = "deliverables/recovery_report.json"
    atomic_write_bytes(out / "recovery_report.json", dumps(report))

    def entry(rel: str) -> dict:
        hashed = _hash_rel(inbox, rel)
        return {"path": f"task_inbox/{task_id}/{rel}", "sha256": hashed["sha256"]}

    orders_rel = "data/orders.csv"
    output_rels = [
        "deliverables/summary.json",
        "deliverables/anomalies.json",
        "deliverables/report.md",
        recovery_rel,
    ]
    manifest = {
        "task_id": task_id,
        "generated_at_utc": ckpt["resume"]["resumed_utc"],
        "component_version": getattr(module, "COMPONENT_VERSION", "ds-t2-worker-1"),
        "input": entry(orders_rel),
        "outputs": [entry(rel) for rel in output_rels],
        "fingerprint_match": _fingerprint_match(ckpt),
        "network": False,
        "paid": False,
    }
    atomic_write_bytes(out / "manifest.json", dumps(manifest))
    # report.md is already in the job's artifact list. These two are new.
    return ["deliverables/recovery_report.json", "deliverables/manifest.json"]


def _write_plain_manifest(module: Any, inbox: Path, out: Path, ckpt: dict) -> None:
    task_id = ckpt["task_id"]

    def entry(rel: str) -> dict:
        hashed = _hash_rel(inbox, rel)
        return {"path": f"task_inbox/{task_id}/{rel}", "sha256": hashed["sha256"]}

    manifest = {
        "task_id": task_id,
        "generated_at_utc": ckpt.get("started_utc") or utc_now(),
        "component_version": getattr(module, "COMPONENT_VERSION", "ds-t2-worker-1"),
        "input": entry("data/orders.csv"),
        "outputs": [
            entry("deliverables/summary.json"),
            entry("deliverables/anomalies.json"),
            entry("deliverables/report.md"),
        ],
        "fingerprint_match": _fingerprint_match(ckpt),
        "network": False,
        "paid": False,
    }
    atomic_write_bytes(out / "manifest.json", dumps(manifest))


def _success_if_stable(ckpt: dict, specs: list[dict], inbox: Path, out: Path) -> dict:
    duplicate = list(ckpt.get("duplicate_jobs") or [])
    if duplicate:
        return _result(ckpt, status="DUPLICATE_JOB", ok=False, deliverables=str(out))
    if not _fingerprint_match(ckpt):
        return _result(ckpt, status="BLOCKED", ok=False, deliverables=str(out))
    if ckpt.get("kill_window"):
        if "sigkill" not in ckpt or "resume" not in ckpt:
            return _result(ckpt, status="SIGKILL_EVENT_MISSING", ok=False, deliverables=str(out))
        return _result(ckpt, status="DONE", ok=True, deliverables=str(out))
    return _result(ckpt, status="DONE_UNINTERRUPTED", ok=True, deliverables=str(out))


def run_resumable(*, module: Any, inbox: Path, out: Path, task_id: str) -> dict:
    specs = [dict(spec) for spec in module.JOB_SPECS]
    state = inbox / "state"
    state.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    ckpt_path = state / "checkpoint.json"
    lock_path = state / "worker.lock"
    lock_fd = open(lock_path, "a+")
    try:
        import fcntl

        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        return _run_locked(
            module=module,
            inbox=inbox,
            out=out,
            task_id=task_id,
            specs=specs,
            ckpt_path=ckpt_path,
        )
    finally:
        try:
            import fcntl

            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()
        try:
            lock_path.unlink()
        except OSError:
            pass


def _run_locked(*, module: Any, inbox: Path, out: Path, task_id: str, specs: list[dict], ckpt_path: Path) -> dict:
    ckpt, error = _load_checkpoint(ckpt_path, task_id)
    if error or ckpt is None:
        return {
            "ok": False,
            "status": error or "CHECKPOINT_UNREADABLE",
            "fingerprint_match": False,
            "duplicate_jobs": [],
            "network": False,
            "paid": False,
            "recovery": False,
        }

    window = ckpt.get("kill_window")
    if isinstance(window, dict) and "resume" not in ckpt:
        event, event_error = _read_sigkill_event(inbox / "state" / "sigkill_event.json", window)
        if event_error or event is None:
            return _result(ckpt, status=event_error or "SIGKILL_EVENT_MISSING", ok=False, deliverables=str(out))
        resumed_utc = utc_strictly_after(event["killed_utc"])
        ckpt["sigkill"] = {
            "killed_pid": int(event["killed_pid"]),
            "killed_utc": event["killed_utc"],
            "signal": 9,
            "kill_checkpoint": event["kill_checkpoint"],
        }
        ckpt["resume"] = {
            "resumed_utc": resumed_utc,
            "resumed_pid": os.getpid(),
            "jobs_done_before": list(window.get("jobs_done") or []),
        }
        _append(
            ckpt,
            {
                "event": "resumed",
                "utc": resumed_utc,
                "jobs_done_before": list(window.get("jobs_done") or []),
                "resumed_pid": os.getpid(),
            },
        )
        _save_checkpoint(ckpt_path, ckpt)

    if specs and all(_reusable(inbox, ckpt, spec["job_id"]) for spec in specs):
        return _success_if_stable(ckpt, specs, inbox, out)

    token_path = inbox / "inject" / "sigkill_at"
    for index, spec in enumerate(specs):
        job_id = spec["job_id"]
        if _reusable(inbox, ckpt, job_id):
            continue
        if _already_committed(ckpt, job_id):
            record = ckpt["jobs"].get(job_id)
            if record and record.get("status") == "DONE":
                return _result(ckpt, status="CORRUPT", ok=False, deliverables=str(out))
            if job_id not in ckpt["duplicate_jobs"]:
                ckpt["duplicate_jobs"].append(job_id)
            _save_checkpoint(ckpt_path, ckpt)
            return _result(ckpt, status="DUPLICATE_JOB", ok=False, deliverables=str(out))
        for prev in specs[:index]:
            if not _reusable(inbox, ckpt, prev["job_id"]):
                return _result(ckpt, status="CORRUPT", ok=False, deliverables=str(out))
        ctx = {
            "inbox": inbox,
            "out": out,
            "task_id": task_id,
            "jobs": json.loads(json.dumps(ckpt["jobs"])),
        }
        outcome = module.execute_job(job_id, ctx)
        if not isinstance(outcome, dict) or not outcome.get("ok"):
            reason = ""
            status = "JOB_FAILED"
            if isinstance(outcome, dict):
                reason = str(outcome.get("reason") or outcome.get("status") or "job_failed")
                status = str(outcome.get("status") or "JOB_FAILED")
            _mark_job_failed(inbox, job_id, reason)
            failed = _result(ckpt, status=status, ok=False, deliverables=str(out))
            failed["reason"] = reason
            return failed
        extra = outcome.get("extra") or {}
        rels = list(outcome.get("artifacts") or [])
        if job_id == specs[-1]["job_id"] and ckpt.get("kill_window"):
            rels.extend(
                _write_recovery_and_manifest(
                    module=module,
                    inbox=inbox,
                    out=out,
                    ckpt=ckpt,
                    specs=specs,
                )
            )
        artifacts = [_hash_rel(inbox, rel) for rel in rels]
        final = index == len(specs) - 1
        if final and not ckpt.get("kill_window"):
            _write_plain_manifest(module, inbox, out, ckpt)
            artifacts.append(_hash_rel(inbox, "deliverables/manifest.json"))
        _commit_job(
            inbox=inbox,
            ckpt=ckpt,
            ckpt_path=ckpt_path,
            specs=specs,
            spec=spec,
            artifacts=artifacts,
            extra=extra,
            final=final,
        )
        boundary = spec.get("after_boundary")
        if boundary and token_path.is_file() and token_path.read_text(encoding="utf-8").strip() == boundary:
            _arm_and_block(
                inbox=inbox,
                ckpt=ckpt,
                ckpt_path=ckpt_path,
                specs=specs,
                boundary=boundary,
                token_path=token_path,
            )
            raise AssertionError("kill window returned; refusing to start the next job")

    if not all(_reusable(inbox, ckpt, spec["job_id"]) for spec in specs):
        return _result(ckpt, status="INCOMPLETE", ok=False, deliverables=str(out))
    return _success_if_stable(ckpt, specs, inbox, out)


def normalize_report_text(text: str, task_id: str, sealed_task_id: str = SEALED_TASK_ID) -> str:
    """Replace this task id with the sealed T1 id. Summary/anomalies are not rewritten."""
    if task_id == sealed_task_id:
        return text
    return text.replace(task_id, sealed_task_id)


def assess_recovery(
    inbox: Path,
    sealed_dir: Path,
    *,
    task_id: str = "DS-T2-20261110",
    kill_checkpoint: str = "after_J2_before_J3",
    sealed_task_id: str = SEALED_TASK_ID,
    orders_sha: str = FROZEN_ORDERS_SHA,
    orders_bytes: int = FROZEN_ORDERS_BYTES,
    orders_lines: int = FROZEN_ORDERS_LINES,
) -> dict:
    """Independent-style check of one inbox. Does not write deliverables."""
    failures: list[str] = []

    def bad(message: str) -> None:
        failures.append(message)

    def sha_file(path: Path) -> str | None:
        try:
            return sha256_bytes(path.read_bytes())
        except OSError:
            return None

    dispatch_path = inbox / "dispatch.json"
    ckpt_path = inbox / "state" / "checkpoint.json"
    event_path = inbox / "state" / "sigkill_event.json"
    window_path = inbox / "state" / "kill_window.json"
    snap_path = inbox / "state" / "dispatch_at_kill.json"
    orders_path = inbox / "data" / "orders.csv"
    summary_path = inbox / "deliverables" / "summary.json"
    anomalies_path = inbox / "deliverables" / "anomalies.json"
    report_path = inbox / "deliverables" / "report.md"
    recovery_path = inbox / "deliverables" / "recovery_report.json"
    manifest_path = inbox / "deliverables" / "manifest.json"

    dispatch = _read_object(dispatch_path, bad, "A-5 dispatch.json")
    ckpt = _read_object(ckpt_path, bad, "A-6 checkpoint.json")
    event = _read_object(event_path, bad, "A-2 sigkill_event.json")
    window_file = _read_object(window_path, bad, "A-6 kill_window.json")
    snap = _read_object(snap_path, bad, "A-6 dispatch_at_kill.json")

    if isinstance(dispatch, dict):
        if dispatch.get("task_id") != task_id:
            bad("A-5 dispatch task_id")
        rows = dispatch.get("jobs")
        if not isinstance(rows, list):
            bad("A-5 dispatch jobs")
        else:
            statuses = {row.get("job_id"): row.get("status") for row in rows if isinstance(row, dict)}
            if [statuses.get(job) for job in ("J1", "J2", "J3", "J4")] != ["DONE", "DONE", "DONE", "DONE"]:
                bad("A-5 dispatch jobs are not all DONE")
        if dispatch.get("executed_by") != "scripts/worker_run_task.py":
            bad("A-5 dispatch executed_by")
        if dispatch.get("fingerprint_match") is not True:
            bad("A-5 fingerprint_match is not true")

    if isinstance(snap, dict):
        if snap.get("executed_utc"):
            bad("A-6 dispatch_at_kill already has executed_utc")
        rows = snap.get("jobs") if isinstance(snap.get("jobs"), list) else []
        statuses = {row.get("job_id"): row.get("status") for row in rows if isinstance(row, dict)}
        if [statuses.get(job) for job in ("J1", "J2", "J3", "J4")] != ["DONE", "DONE", "PENDING", "PENDING"]:
            bad("A-6 dispatch_at_kill statuses are not J1 J2 DONE and J3 J4 PENDING")

    window = None
    if isinstance(ckpt, dict):
        if ckpt.get("task_id") != task_id:
            bad("A-5 checkpoint task_id")
        window = ckpt.get("kill_window")
        journal = ckpt.get("journal")
        if not isinstance(window, dict):
            bad("A-6 checkpoint has no kill_window")
        elif window.get("kill_checkpoint") != kill_checkpoint:
            bad("A-2 kill_checkpoint")
        elif window.get("jobs_done") != ["J1", "J2"] or window.get("jobs_not_started") != ["J3", "J4"]:
            bad("A-6 kill_window job lists")
        else:
            cmdline = str(window.get("cmdline") or "")
            if "worker_run_task.py" not in cmdline or task_id not in cmdline:
                bad("A-6 kill_window cmdline is not the product entry")
        if not isinstance(journal, list):
            bad("A-6 journal missing")
            journal = []
        _check_journal(journal, bad, kill_checkpoint)
        if ckpt.get("duplicate_jobs") != []:
            bad("A-3 checkpoint duplicate_jobs")
        commits = [event for event in journal if isinstance(event, dict) and event.get("event") == "job_committed"]
        keys = [event.get("idempotency_key") for event in commits]
        expected = [f"{task_id}:{job}" for job in ("J1", "J2", "J3", "J4")]
        if keys != expected:
            bad("A-6 journal idempotency keys are not one per job")

    if isinstance(window_file, dict) and isinstance(window, dict):
        if window_file.get("pid") != window.get("pid") or window_file.get("kill_checkpoint") != kill_checkpoint:
            bad("A-6 kill_window.json does not match checkpoint")

    if isinstance(event, dict) and isinstance(window, dict):
        try:
            if int(event.get("killed_pid")) != int(window.get("pid")):
                bad("A-2 killed_pid does not match kill_window")
            if int(event.get("signal")) != 9:
                bad("A-2 signal is not SIGKILL")
            if event.get("kill_checkpoint") != kill_checkpoint:
                bad("A-2 event kill_checkpoint")
            if parse_utc(event["killed_utc"]) < parse_utc(window["ready_utc"]):
                bad("A-2 killed_utc is before the checkpoint was durable")
        except (TypeError, ValueError, KeyError):
            bad("A-2 sigkill event fields")

    recovery = _read_object(recovery_path, bad, "A-2 recovery_report.json")
    if isinstance(recovery, dict):
        if tuple(recovery.keys()) != RECOVERY_KEYS:
            bad("A-2 recovery_report.json keys")
        if recovery.get("task_id") != task_id:
            bad("A-5 recovery task_id")
        if recovery.get("kill_checkpoint") != kill_checkpoint:
            bad("A-2 recovery kill_checkpoint")
        if recovery.get("jobs_done_before") != ["J1", "J2"]:
            bad("A-6 jobs_done_before")
        if recovery.get("jobs_done_after") != ["J1", "J2", "J3", "J4"]:
            bad("A-6 jobs_done_after")
        if recovery.get("duplicate_jobs") != []:
            bad("A-3 duplicate_jobs")
        if recovery.get("idempotency_keys") != []:
            bad("A-3 idempotency_keys collision list")
        try:
            killed = parse_utc(recovery["killed_utc"])
            resumed = parse_utc(recovery["resumed_utc"])
            if not killed < resumed:
                bad("A-2 killed_utc is not before resumed_utc")
            if isinstance(window, dict) and killed < parse_utc(window["ready_utc"]):
                bad("A-2 recovery killed_utc is before ready_utc")
        except (TypeError, ValueError, KeyError):
            bad("A-2 recovery timestamps")
        if isinstance(event, dict) and recovery.get("killed_utc") != event.get("killed_utc"):
            bad("A-2 recovery killed_utc does not match sigkill event")
        if isinstance(event, dict):
            try:
                if int(recovery.get("killed_pid")) != int(event.get("killed_pid")):
                    bad("A-2 recovery killed_pid does not match sigkill event")
            except (TypeError, ValueError):
                bad("A-2 recovery killed_pid")
        if isinstance(ckpt, dict):
            resume = ckpt.get("resume") or {}
            sigkill = ckpt.get("sigkill") or {}
            if recovery.get("resumed_utc") != resume.get("resumed_utc"):
                bad("A-6 recovery resumed_utc does not match checkpoint")
            if recovery.get("killed_pid") != sigkill.get("killed_pid"):
                bad("A-6 recovery killed_pid does not match checkpoint")

    orders_digest = None
    if not orders_path.is_file():
        bad("A-4 orders.csv missing")
    else:
        raw = orders_path.read_bytes()
        orders_digest = sha256_bytes(raw)
        if (
            orders_digest != orders_sha
            or len(raw) != orders_bytes
            or len(raw.splitlines()) != orders_lines
            or raw.count(b"\n") != orders_lines
            or raw.startswith(b"\xef\xbb\xbf")
        ):
            bad("A-1 orders.csv fingerprint mismatch")

    for label, path, sealed_name in (
        ("summary.json", summary_path, "summary.json"),
        ("anomalies.json", anomalies_path, "anomalies.json"),
    ):
        sealed_path = sealed_dir / sealed_name
        try:
            got = path.read_bytes()
            sealed = sealed_path.read_bytes()
            json.loads(got)
            json.loads(sealed)
        except (OSError, json.JSONDecodeError):
            bad(f"A-4 {label} does not parse")
            continue
        if got != sealed:
            bad(f"A-1 {label} bytes differ from sealed T1")

    report_digest = None
    normalized_digest = None
    try:
        report_text = report_path.read_text(encoding="utf-8")
        normalized = normalize_report_text(report_text, task_id, sealed_task_id).encode("utf-8")
        sealed_report = (sealed_dir / "report.md").read_bytes()
        report_digest = sha256_bytes(report_text.encode("utf-8"))
        normalized_digest = sha256_bytes(normalized)
        if task_id not in report_text:
            bad("A-5 report.md is not bound to task_id")
        if normalized != sealed_report:
            bad("A-1 report.md normalized bytes differ from sealed T1")
    except OSError:
        bad("A-4 report.md missing")

    manifest = _read_object(manifest_path, bad, "A-4 manifest.json")
    if isinstance(manifest, dict):
        if manifest.get("task_id") != task_id:
            bad("A-5 manifest task_id")
        if manifest.get("fingerprint_match") is not True:
            bad("A-1 manifest fingerprint_match")
        if manifest.get("network") is not False or manifest.get("paid") is not False:
            bad("manifest network or paid flag")
        input_meta = manifest.get("input") if isinstance(manifest.get("input"), dict) else {}
        if input_meta.get("sha256") != orders_digest:
            bad("A-4 manifest input sha256")
        outputs = manifest.get("outputs")
        expected_names = ["summary.json", "anomalies.json", "report.md", "recovery_report.json"]
        if not isinstance(outputs, list) or [Path(item.get("path", "")).name for item in outputs if isinstance(item, dict)] != expected_names:
            bad("A-4 manifest outputs")
        else:
            for item in outputs:
                rel_name = Path(item["path"]).name
                actual = sha_file(inbox / "deliverables" / rel_name)
                if item.get("sha256") != actual or task_id not in str(item.get("path")):
                    bad(f"A-4 manifest hash for {rel_name}")

    return {
        "ok": not failures,
        "failures": failures,
        "fingerprint_match": orders_digest == orders_sha,
        "sha256": {
            "orders": orders_digest,
            "summary": sha_file(summary_path),
            "anomalies": sha_file(anomalies_path),
            "report": report_digest,
            "report_normalized": normalized_digest,
            "recovery_report": sha_file(recovery_path),
            "manifest": sha_file(manifest_path),
        },
    }


def _read_object(path: Path, bad, label: str) -> Any:
    if not path.is_file():
        bad(f"{label} missing")
        return None
    try:
        return _load_json(path)
    except json.JSONDecodeError:
        bad(f"{label} does not parse")
        return None


def _check_journal(journal: list, bad, kill_checkpoint: str) -> None:
    def positions(event_name: str, job_id: str | None = None) -> list[int]:
        found = []
        for index, event in enumerate(journal):
            if not isinstance(event, dict) or event.get("event") != event_name:
                continue
            if job_id is not None and event.get("job_id") != job_id:
                continue
            found.append(index)
        return found

    needed = {
        "J1": positions("job_committed", "J1"),
        "J2": positions("job_committed", "J2"),
        "J3": positions("job_committed", "J3"),
        "J4": positions("job_committed", "J4"),
        "kill": positions("kill_window_open"),
        "resume": positions("resumed"),
    }
    if any(len(indexes) != 1 for indexes in needed.values()):
        bad("A-6 journal does not contain exactly one commit per job plus one kill and one resume")
        return
    order = [
        needed["J1"][0],
        needed["J2"][0],
        needed["kill"][0],
        needed["resume"][0],
        needed["J3"][0],
        needed["J4"][0],
    ]
    if order != sorted(order):
        bad("A-6 journal order is not J1 J2 kill resume J3 J4")
    kill_event = journal[needed["kill"][0]]
    if kill_event.get("kill_checkpoint") != kill_checkpoint or kill_event.get("jobs_done") != ["J1", "J2"]:
        bad("A-6 kill_window_open event")
    resume_event = journal[needed["resume"][0]]
    if resume_event.get("jobs_done_before") != ["J1", "J2"]:
        bad("A-6 resumed event jobs_done_before")
