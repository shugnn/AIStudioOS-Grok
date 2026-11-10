"""SIGKILL after J2, then resume through scripts/worker_run_task.py."""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from control_plane.worker_resume import (
    _write_recovery_and_manifest,
    assess_recovery,
    sha256_bytes,
)

TASK_ID = "DS-T2-20261110"
USED_KEYS = [f"{TASK_ID}:{job}" for job in ("J1", "J2", "J3", "J4")]
SEALED = REPO / "tests" / "fixtures" / "ds_t1_sealed"
PUBLISHED = {
    "orders.csv": "633aded091b1da111f4c3c9c378c975d3bdddf17e85a0fd3b001c7e4ddbf7ffe",
    "summary.json": "1f1b56e79459084f1fa1f565320e70433013ba6ee32fdb4521c914d108b5eec2",
    "anomalies.json": "a5d368e0f7c5970f38b5fd2c093e8b6448bf7ff00996521275bd23624a3606c1",
    "report.md": "2e337adc347783fa5ad31513065e43c3b011fcee940bc49df430bfaa5b1ebf1f",
}


def _load_jobs():
    path = REPO / "task_inbox" / TASK_ID / "worker_jobs.py"
    spec = importlib.util.spec_from_file_location("ds_t2_worker_jobs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare(root: Path, *, arm_kill: bool) -> Path:
    inbox = root / TASK_ID
    if inbox.exists():
        shutil.rmtree(inbox)
    inbox.mkdir(parents=True)
    shutil.copy(REPO / "task_inbox" / TASK_ID / "worker_jobs.py", inbox / "worker_jobs.py")
    shutil.copy(REPO / "task_inbox" / TASK_ID / "dispatch.json", inbox / "dispatch.json")
    if arm_kill:
        inject = inbox / "inject"
        inject.mkdir()
        (inject / "sigkill_at").write_text("after_J2_before_J3\n", encoding="utf-8")
    return inbox


def _env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env["AISTUDIO_INBOX_ROOT"] = str(root)
    return env


def _command() -> list[str]:
    return [sys.executable, str(REPO / "scripts" / "worker_run_task.py"), "--task-id", TASK_ID]


def _run(root: Path, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _command(),
        cwd=REPO,
        env=_env(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _write_event(inbox: Path, pid: int) -> str:
    killed_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = {
        "killed_pid": pid,
        "killed_utc": killed_utc,
        "kill_checkpoint": "after_J2_before_J3",
        "signal": 9,
    }
    path = inbox / "state" / "sigkill_event.json"
    data = (json.dumps(event, indent=2) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return killed_utc


def _kill_after_j2(root: Path) -> dict:
    inbox = root / TASK_ID
    proc = subprocess.Popen(
        _command(),
        cwd=REPO,
        env=_env(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    window_path = inbox / "state" / "kill_window.json"
    token = inbox / "inject" / "sigkill_at"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if window_path.is_file() and not token.exists():
                break
            if proc.poll() is not None:
                out, err = proc.communicate()
                raise AssertionError(
                    f"worker exited before kill window: code={proc.returncode}\n{out}\n{err}"
                )
            time.sleep(0.05)
        else:
            raise AssertionError("kill window did not open")
        window = json.loads(window_path.read_text(encoding="utf-8"))
        assert window["pid"] == proc.pid
        assert window["kill_checkpoint"] == "after_J2_before_J3"
        assert window["jobs_done"] == ["J1", "J2"]
        assert window["jobs_not_started"] == ["J3", "J4"]
        assert not (inbox / "deliverables" / "anomalies.json").exists()
        summary = inbox / "deliverables" / "summary.json"
        assert summary.is_file()
        st = summary.stat()
        os.kill(window["pid"], signal.SIGKILL)
        code = proc.wait(timeout=10)
        assert code in (-9, -signal.SIGKILL, 137)
        killed_utc = _write_event(inbox, window["pid"])
        return {
            "pid": window["pid"],
            "killed_utc": killed_utc,
            "summary_ino": st.st_ino,
            "summary_bytes": summary.read_bytes(),
        }
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass


def _commit(job_id: str) -> dict:
    return {
        "event": "job_committed",
        "job_id": job_id,
        "idempotency_key": f"{TASK_ID}:{job_id}",
    }


def test_writer_lists_keys_used_without_inventing_a_second_final_key(tmp_path: Path):
    inbox = tmp_path / TASK_ID
    out = inbox / "deliverables"
    (inbox / "data").mkdir(parents=True)
    out.mkdir()
    (inbox / "data" / "orders.csv").write_bytes(b"order\n")
    (out / "summary.json").write_text("{}\n", encoding="utf-8")
    (out / "anomalies.json").write_text("[]\n", encoding="utf-8")
    (out / "report.md").write_text("report\n", encoding="utf-8")
    specs = [{"job_id": job} for job in ("J1", "J2", "J3", "J4")]
    module = type("Module", (), {"COMPONENT_VERSION": "ds-t2-worker-1"})()

    def checkpoint(journal: list) -> dict:
        return {
            "task_id": TASK_ID,
            "journal": journal,
            "duplicate_jobs": [],
            "kill_window": {
                "kill_checkpoint": "after_J2_before_J3",
                "jobs_done": ["J1", "J2"],
            },
            "sigkill": {"killed_pid": 2406, "killed_utc": "2026-11-10T08:29:48Z"},
            "resume": {"resumed_utc": "2026-11-10T08:29:49Z"},
        }

    before_j4 = [
        _commit("J1"),
        _commit("J2"),
        {"event": "kill_window_open"},
        {"event": "resumed"},
        _commit("J3"),
    ]
    _write_recovery_and_manifest(
        module=module,
        inbox=inbox,
        out=out,
        ckpt=checkpoint(before_j4),
        specs=specs,
    )
    written = json.loads((out / "recovery_report.json").read_text(encoding="utf-8"))
    assert written["idempotency_keys"] == USED_KEYS
    assert written["duplicate_jobs"] == []
    assert written["killed_pid"] == 2406
    assert written["killed_utc"] == "2026-11-10T08:29:48Z"
    assert written["resumed_utc"] == "2026-11-10T08:29:49Z"

    _write_recovery_and_manifest(
        module=module,
        inbox=inbox,
        out=out,
        ckpt=checkpoint(before_j4 + [_commit("J4")]),
        specs=specs,
    )
    finished = json.loads((out / "recovery_report.json").read_text(encoding="utf-8"))
    assert finished["idempotency_keys"] == USED_KEYS

    repeated = before_j4 + [_commit("J4"), _commit("J2")]
    _write_recovery_and_manifest(
        module=module,
        inbox=inbox,
        out=out,
        ckpt=checkpoint(repeated),
        specs=specs,
    )
    collided = json.loads((out / "recovery_report.json").read_text(encoding="utf-8"))
    assert collided["idempotency_keys"] == USED_KEYS + [f"{TASK_ID}:J2"]
    assert collided["duplicate_jobs"] == []


def test_sealed_fixture_hashes():
    for name, digest in PUBLISHED.items():
        if name == "orders.csv":
            continue
        assert sha256_bytes((SEALED / name).read_bytes()) == digest


def test_generator_and_normalized_report_match_t1():
    jobs = _load_jobs()
    raw = jobs.render_orders_csv().encode("utf-8")
    info = jobs.fingerprint(raw)
    assert info["match_expected"] is True
    assert info["sha256"] == PUBLISHED["orders.csv"]
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    summary = jobs.summarize(rows)
    anomalies = jobs.find_anomalies(rows)
    summary_bytes = (json.dumps(summary, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    anomalies_bytes = (json.dumps(anomalies, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    assert summary_bytes == (SEALED / "summary.json").read_bytes()
    assert anomalies_bytes == (SEALED / "anomalies.json").read_bytes()
    assert sha256_bytes(summary_bytes) == PUBLISHED["summary.json"]
    assert sha256_bytes(anomalies_bytes) == PUBLISHED["anomalies.json"]
    report = jobs.build_report(TASK_ID, info, summary, anomalies)
    normalized = report.replace(TASK_ID, "DS-T1-20261108").encode("utf-8")
    assert normalized == (SEALED / "report.md").read_bytes()
    assert sha256_bytes(normalized) == PUBLISHED["report.md"]
    assert [spec["job_id"] for spec in jobs.JOB_SPECS] == ["J1", "J2", "J3", "J4"]
    assert jobs.JOB_SPECS[1]["after_boundary"] == "after_J2_before_J3"


def test_resume_via_product_entry_matches_t1(tmp_path: Path):
    root = tmp_path / "root"
    _prepare(root, arm_kill=True)
    killed = _kill_after_j2(root)
    second = _run(root)
    assert second.returncode == 0, second.stdout + "\n" + second.stderr
    payload = json.loads(second.stdout)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "DONE"
    assert payload["result"]["recovery"] is True
    assert payload["result"]["fingerprint_match"] is True
    assert payload["result"]["duplicate_jobs"] == []
    assert payload["result"]["killed_pid"] == killed["pid"]
    inbox = root / TASK_ID
    summary = inbox / "deliverables" / "summary.json"
    assert summary.stat().st_ino == killed["summary_ino"]
    assert summary.read_bytes() == killed["summary_bytes"]
    third = _run(root)
    assert third.returncode == 0, third.stdout + "\n" + third.stderr
    third_payload = json.loads(third.stdout)
    assert third_payload["result"]["status"] == "DONE"
    assert third_payload["result"]["duplicate_jobs"] == []
    assert summary.stat().st_ino == killed["summary_ino"]
    assessment = assess_recovery(inbox, SEALED)
    assert assessment["ok"] is True, assessment["failures"]
    assert assessment["fingerprint_match"] is True
    assert assessment["sha256"]["orders"] == PUBLISHED["orders.csv"]
    assert assessment["sha256"]["summary"] == PUBLISHED["summary.json"]
    assert assessment["sha256"]["anomalies"] == PUBLISHED["anomalies.json"]
    assert assessment["sha256"]["report_normalized"] == PUBLISHED["report.md"]
    checkpoint = json.loads((inbox / "state" / "checkpoint.json").read_text(encoding="utf-8"))
    commits = [event["job_id"] for event in checkpoint["journal"] if event["event"] == "job_committed"]
    assert commits == ["J1", "J2", "J3", "J4"]
    report = json.loads((inbox / "deliverables" / "recovery_report.json").read_text(encoding="utf-8"))
    assert report["duplicate_jobs"] == []
    journal_keys = [
        event["idempotency_key"]
        for event in checkpoint["journal"]
        if event["event"] == "job_committed"
    ]
    assert journal_keys == USED_KEYS
    assert report["idempotency_keys"] == USED_KEYS
    assert report["kill_checkpoint"] == "after_J2_before_J3"
    assert report["jobs_done_before"] == ["J1", "J2"]
    assert report["jobs_done_after"] == ["J1", "J2", "J3", "J4"]
    assert report["killed_pid"] == killed["pid"]
    assert report["killed_utc"] < report["resumed_utc"]


def test_forged_recovery_without_checkpoint_fails(tmp_path: Path):
    inbox = tmp_path / TASK_ID
    (inbox / "deliverables").mkdir(parents=True)
    for name in ("summary.json", "anomalies.json"):
        shutil.copy(SEALED / name, inbox / "deliverables" / name)
    report = (SEALED / "report.md").read_text(encoding="utf-8").replace("DS-T1-20261108", TASK_ID)
    (inbox / "deliverables" / "report.md").write_text(report, encoding="utf-8")
    fake = {
        "task_id": TASK_ID,
        "killed_pid": 4242,
        "kill_checkpoint": "after_J2_before_J3",
        "killed_utc": "2026-11-10T00:00:01Z",
        "resumed_utc": "2026-11-10T00:00:02Z",
        "jobs_done_before": ["J1", "J2"],
        "jobs_done_after": ["J1", "J2", "J3", "J4"],
        "duplicate_jobs": [],
        "idempotency_keys": [],
    }
    (inbox / "deliverables" / "recovery_report.json").write_text(
        json.dumps(fake, indent=2) + "\n", encoding="utf-8"
    )
    (inbox / "dispatch.json").write_text(
        json.dumps(
            {
                "task_id": TASK_ID,
                "executed_by": "scripts/worker_run_task.py",
                "fingerprint_match": True,
                "jobs": [{"job_id": job, "status": "DONE"} for job in ("J1", "J2", "J3", "J4")],
            }
        ),
        encoding="utf-8",
    )
    verdict = assess_recovery(inbox, SEALED)
    assert verdict["ok"] is False
    assert any("checkpoint" in item for item in verdict["failures"])


def test_forged_fields_and_tampered_summary_fail(tmp_path: Path):
    root = tmp_path / "root"
    _prepare(root, arm_kill=True)
    _kill_after_j2(root)
    second = _run(root)
    assert second.returncode == 0, second.stdout + second.stderr
    inbox = root / TASK_ID
    report_path = inbox / "deliverables" / "recovery_report.json"
    original = report_path.read_text(encoding="utf-8")
    report = json.loads(original)
    report["duplicate_jobs"] = ["J2"]
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    verdict = assess_recovery(inbox, SEALED)
    assert verdict["ok"] is False
    assert any(item.startswith("A-3") for item in verdict["failures"])

    report["duplicate_jobs"] = []
    report["idempotency_keys"] = ["forged-key"]
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    verdict = assess_recovery(inbox, SEALED)
    assert verdict["ok"] is False
    assert any("idempotency_keys" in item for item in verdict["failures"])

    report["idempotency_keys"] = []
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    verdict = assess_recovery(inbox, SEALED)
    assert verdict["ok"] is False
    assert any("idempotency_keys" in item for item in verdict["failures"])

    report_path.write_text(original, encoding="utf-8")
    ckpt_path = inbox / "state" / "checkpoint.json"
    ckpt_original = ckpt_path.read_text(encoding="utf-8")
    ckpt = json.loads(ckpt_original)
    repeated = dict(next(event for event in ckpt["journal"] if event.get("job_id") == "J2"))
    repeated["seq"] = len(ckpt["journal"]) + 1
    ckpt["journal"].append(repeated)
    ckpt_path.write_text(json.dumps(ckpt, indent=2) + "\n", encoding="utf-8")
    listed = json.loads(original)
    listed["idempotency_keys"] = list(listed["idempotency_keys"]) + [f"{TASK_ID}:J2"]
    report_path.write_text(json.dumps(listed, indent=2) + "\n", encoding="utf-8")
    verdict = assess_recovery(inbox, SEALED)
    assert verdict["ok"] is False
    assert any(item.startswith("A-3") and "idempotency" in item for item in verdict["failures"])
    ckpt_path.write_text(ckpt_original, encoding="utf-8")
    report_path.write_text(original, encoding="utf-8")
    swapped = json.loads(original)
    swapped["killed_utc"], swapped["resumed_utc"] = swapped["resumed_utc"], swapped["killed_utc"]
    report_path.write_text(json.dumps(swapped, indent=2) + "\n", encoding="utf-8")
    verdict = assess_recovery(inbox, SEALED)
    assert verdict["ok"] is False
    assert any(item.startswith("A-2") for item in verdict["failures"])

    report_path.write_text(original, encoding="utf-8")
    summary = inbox / "deliverables" / "summary.json"
    summary.write_bytes(summary.read_bytes().replace(b"5983804.03", b"0000000.00"))
    verdict = assess_recovery(inbox, SEALED)
    assert verdict["ok"] is False
    assert any("summary.json" in item for item in verdict["failures"])


def test_corrupt_summary_is_not_rewritten(tmp_path: Path):
    root = tmp_path / "root"
    _prepare(root, arm_kill=True)
    _kill_after_j2(root)
    assert _run(root).returncode == 0
    summary = root / TASK_ID / "deliverables" / "summary.json"
    tampered = summary.read_bytes().replace(b"5983804.03", b"5983804.04")
    summary.write_bytes(tampered)
    result = _run(root)
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "CORRUPT"
    assert summary.read_bytes() == tampered


def test_missing_sigkill_event_does_not_start_j3(tmp_path: Path):
    root = tmp_path / "root"
    _prepare(root, arm_kill=True)
    _kill_after_j2(root)
    (root / TASK_ID / "state" / "sigkill_event.json").unlink()
    result = _run(root)
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "SIGKILL_EVENT_MISSING"
    assert not (root / TASK_ID / "deliverables" / "anomalies.json").exists()


def test_pid_mismatch_does_not_resume(tmp_path: Path):
    root = tmp_path / "root"
    _prepare(root, arm_kill=True)
    killed = _kill_after_j2(root)
    event_path = root / TASK_ID / "state" / "sigkill_event.json"
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["killed_pid"] = killed["pid"] + 1
    event_path.write_text(json.dumps(event, indent=2) + "\n", encoding="utf-8")
    result = _run(root)
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "KILLED_PID_MISMATCH"
    assert not (root / TASK_ID / "deliverables" / "anomalies.json").exists()


def test_uninterrupted_run_is_not_a_recovery(tmp_path: Path):
    root = tmp_path / "root"
    _prepare(root, arm_kill=False)
    result = _run(root)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "DONE_UNINTERRUPTED"
    assert payload["result"]["recovery"] is False
    assert payload["result"]["duplicate_jobs"] == []
    verdict = assess_recovery(root / TASK_ID, SEALED)
    assert verdict["ok"] is False


def test_duplicate_journal_is_not_rerun(tmp_path: Path):
    root = tmp_path / "root"
    _prepare(root, arm_kill=True)
    _kill_after_j2(root)
    assert _run(root).returncode == 0
    inbox = root / TASK_ID
    ckpt_path = inbox / "state" / "checkpoint.json"
    ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
    del ckpt["jobs"]["J2"]
    ckpt_path.write_text(json.dumps(ckpt, indent=2) + "\n", encoding="utf-8")
    (inbox / "deliverables" / "summary.json").unlink()
    result = _run(root)
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["result"]["status"] == "DUPLICATE_JOB"
    assert "J2" in payload["result"]["duplicate_jobs"]
    assert not (inbox / "deliverables" / "summary.json").exists()
