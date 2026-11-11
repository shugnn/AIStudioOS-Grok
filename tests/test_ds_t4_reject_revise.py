"""DS-T4-20261112 reject-then-revise. No paid API. No precomputed v2 totals."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_plane.appointment_rules import (  # noqa: E402
    aggregate,
    load_appointments,
    load_contract,
)
from control_plane.contract_verifier import judge  # noqa: E402
from control_plane.reject_revise import BLOCKED_TASK_IDS  # noqa: E402

TASK = ROOT / "task_inbox" / "DS-T4-20261112"
EXPECTED_SHA256 = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"
EXPECTED_BYTES = 12350
T1_SHA256 = {
    "task_inbox/DS-T1-20261108/TASK.md": "7bdbd16bbc7714b2ba669b029635bdf48e270505936e36441d7cd678cc81983b",
    "task_inbox/DS-T1-20261108/dispatch.json": "7647386e4b4126569d858547c7db6e0b49b9521edd1f01fe1f45bbc085d21eae",
    "task_inbox/DS-T1-20261108/worker_jobs.py": "0681e5926a09d4a4c88c68e62718f50eae31966fe1491a3d4dc5b7f4e9f8f634",
}


def _load_worker():
    path = TASK / "worker_jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_ds_t4", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _contract() -> dict:
    return load_contract(TASK / "contract.json")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _independent(rows: list[dict], contract: dict) -> dict:
    departments = list(contract["departments"])
    status = contract["count_status"]
    counts = {dept: 0 for dept in departments}
    cents = {dept: 0 for dept in departments}
    months: dict[str, int] = {}
    total = 0
    for row in rows:
        if row["status"] != status:
            continue
        dept = row["dept"]
        fee = row["fee_cents"]
        month = row["visit_date"][:7]
        counts[dept] += 1
        cents[dept] += fee
        months[month] = months.get(month, 0) + fee
        total += fee

    def money(value: int) -> str:
        return f"{value // 100}.{value % 100:02d}"

    return {
        "total_revenue": money(total),
        "by_dept": {dept: {"count": counts[dept], "revenue": money(cents[dept])} for dept in departments},
        "by_month": {month: money(months[month]) for month in sorted(months)},
    }


def _toy_rows() -> list[dict]:
    return [
        {"appt_id": "1", "patient_id": "P0001", "dept": "med", "visit_date": "2026-02-01", "fee_cents": 100, "status": "completed"},
        {"appt_id": "2", "patient_id": "P0002", "dept": "derm", "visit_date": "2026-01-15", "fee_cents": 250, "status": "cancelled"},
        {"appt_id": "3", "patient_id": "P0003", "dept": "surg", "visit_date": "2026-01-02", "fee_cents": 50, "status": "completed"},
        {"appt_id": "4", "patient_id": "P0004", "dept": "ped", "visit_date": "2026-03-03", "fee_cents": 80, "status": "no_show"},
    ]


def _copy_inbox(tmp_path: Path) -> Path:
    dst = tmp_path / "DS-T4-20261112"
    dst.mkdir()
    for name in ("worker_jobs.py", "generate_appts.py", "candidate_v1.json", "contract.json", "dispatch.json"):
        shutil.copy(TASK / name, dst / name)
    return dst


def test_generator_source_keeps_random_consumption_order():
    text = (TASK / "generate_appts.py").read_text(encoding="utf-8")
    assert not text.startswith("\ufeff")
    assert "\r" not in text
    assert "random.Random(20261112)" in text
    line = 'st = "completed" if rng.randrange(100) < 80 else ("cancelled" if rng.randrange(2) == 0 else "no_show")'
    assert line in text
    assert text.index("rng.randrange(100)") < text.index("rng.randrange(2)")


def test_prepare_writes_frozen_fingerprint(tmp_path):
    inbox = tmp_path / "DS-T4-20261112"
    inbox.mkdir()
    shutil.copy(TASK / "generate_appts.py", inbox / "generate_appts.py")
    result = _load_worker().prepare_input(inbox=inbox)
    assert result["ok"] is True
    assert result["error"] is None
    written = (inbox / "data" / "appts.csv").read_bytes()
    assert hashlib.sha256(written).hexdigest() == EXPECTED_SHA256
    assert len(written) == EXPECTED_BYTES
    assert written.count(b"\n") == 301
    assert written.endswith(b"\n")
    assert not written.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in written


def test_prepare_does_not_rewrite_csv_to_force_hash(tmp_path):
    inbox = tmp_path / "DS-T4-20261112"
    inbox.mkdir()
    text = (TASK / "generate_appts.py").read_text(encoding="utf-8")
    (inbox / "generate_appts.py").write_text(text.replace("Random(20261112)", "Random(1)"), encoding="utf-8")
    result = _load_worker().prepare_input(inbox=inbox)
    assert result["ok"] is False
    assert result["error"] == "fingerprint_mismatch"
    assert result["sha256"] != EXPECTED_SHA256
    assert result["bytes"] != EXPECTED_BYTES or result["sha256"] != EXPECTED_SHA256


def test_roles_do_not_import_each_other():
    verifier = _imports(ROOT / "control_plane" / "contract_verifier.py")
    worker = _imports(TASK / "worker_jobs.py")
    orchestrator = _imports(ROOT / "control_plane" / "reject_revise.py")
    assert "control_plane.contract_verifier" not in worker
    assert not any("worker_jobs" in name for name in verifier)
    assert "control_plane.contract_verifier" not in orchestrator
    assert not any("worker_jobs" in name for name in orchestrator)


def test_blocked_ids_match_between_entry_and_orchestrator():
    spec = importlib.util.spec_from_file_location("worker_entry_t4", ROOT / "scripts" / "worker_run_task.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.BLOCKED_TASK_IDS == BLOCKED_TASK_IDS
    assert "DS-T1-20261108" in BLOCKED_TASK_IDS


def test_t1_files_stay_byte_identical():
    for rel, digest in T1_SHA256.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest


def test_published_v1_keeps_defective_literals():
    text = (TASK / "candidate_v1.json").read_text(encoding="utf-8")
    assert "18093.9" in text
    assert "18093.90" not in text
    assert "21773.7" in text
    candidate = json.loads(text)
    assert list(candidate["by_month"]) != sorted(candidate["by_month"])
    assert "derm" not in candidate["by_dept"]
    assert isinstance(candidate["total_revenue"], float)


def test_each_rule_can_fail_on_its_own():
    contract = _contract()
    rows = _toy_rows()
    good = aggregate(rows, contract)
    assert good == _independent(rows, contract)
    assert good["by_dept"]["ped"]["count"] == 0
    assert good["by_dept"]["derm"]["count"] == 0
    assert judge(good, rows, contract) == {"verdict": "ACCEPTED", "checks": 4}

    only_r1 = json.loads(json.dumps(good))
    only_r1["total_revenue"] = 1.5
    assert [item["rule"] for item in judge(only_r1, rows, contract)["reasons"]] == ["R1"]

    only_r2 = json.loads(json.dumps(good))
    del only_r2["by_dept"]["ped"]
    assert [item["rule"] for item in judge(only_r2, rows, contract)["reasons"]] == ["R2"]

    only_r3 = json.loads(json.dumps(good))
    only_r3["by_month"] = {key: only_r3["by_month"][key] for key in reversed(list(only_r3["by_month"]))}
    assert [item["rule"] for item in judge(only_r3, rows, contract)["reasons"]] == ["R3"]

    only_r4 = json.loads(json.dumps(good))
    only_r4["total_revenue"] = "4.80"
    rejected = judge(only_r4, rows, contract)
    assert [item["rule"] for item in rejected["reasons"]] == ["R4"]
    assert "cancelled" in rejected["reasons"][0]["detail"] or "no_show" in rejected["reasons"][0]["detail"] or "completed" in rejected["reasons"][0]["detail"]


def test_official_v1_is_rejected_on_all_four_rules():
    contract = _contract()
    inbox = TASK
    # Use a generated copy so this test does not require the committed csv yet.
    # The fingerprint test already locks the generator. Here we judge the published candidate.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "DS-T4-20261112"
        folder.mkdir()
        shutil.copy(TASK / "generate_appts.py", folder / "generate_appts.py")
        assert _load_worker().prepare_input(inbox=folder)["ok"] is True
        rows = load_appointments(folder / "data" / "appts.csv")
    candidate = json.loads((inbox / "candidate_v1.json").read_text(encoding="utf-8"))
    verdict = judge(candidate, rows, contract)
    assert set(verdict) == {"verdict", "reasons"}
    assert verdict["verdict"] == "REJECTED"
    assert [item["rule"] for item in verdict["reasons"]] == ["R1", "R2", "R3", "R4"]
    details = {item["rule"]: item["detail"] for item in verdict["reasons"]}
    assert "float" in details["R1"]
    assert "derm" in details["R2"]
    assert "ascending" in details["R3"]
    assert "by_dept.med count/revenue" not in details["R4"]
    assert "by_dept.derm" in details["R4"]
    assert "cancelled and no_show" in details["R4"]
    assert all(set(item) == {"rule", "detail"} for item in verdict["reasons"])


def test_revise_follows_verdict_and_does_not_write_one(tmp_path):
    inbox = _copy_inbox(tmp_path)
    worker = _load_worker()
    assert worker.prepare_input(inbox=inbox)["ok"] is True
    rows = load_appointments(inbox / "data" / "appts.csv")
    contract = load_contract(inbox / "contract.json")
    candidate = json.loads((inbox / "candidate_v1.json").read_text(encoding="utf-8"))
    verdict = judge(candidate, rows, contract)
    out = inbox / "deliverables"
    out.mkdir()
    (out / "verdict_v1.json").write_text(json.dumps(verdict) + "\n", encoding="utf-8")
    result = worker.revise(inbox=inbox, task_id="DS-T4-20261112")
    assert result["ok"] is True
    assert result["wrote"] == ["deliverables/candidate_v2.json", "deliverables/revision_log.json"]
    assert not (out / "verdict_v2.json").exists()
    v2 = json.loads((out / "candidate_v2.json").read_text(encoding="utf-8"))
    assert v2 == _independent(rows, contract)
    assert v2["total_revenue"] != f"{candidate['total_revenue']:.2f}"
    assert list(v2["by_dept"]) == ["med", "surg", "ped", "derm"]
    assert list(v2["by_month"]) == sorted(v2["by_month"])
    assert isinstance(v2["total_revenue"], str)
    accepted = judge(v2, rows, contract)
    assert accepted == {"verdict": "ACCEPTED", "checks": 4}
    log = json.loads((out / "revision_log.json").read_text(encoding="utf-8"))
    assert [entry["rule"] for entry in log["entries"]] == ["R1", "R2", "R3", "R4"]
    for entry in log["entries"]:
        assert entry["addressed"] is True
        assert entry["reason"]
        assert entry["change"].startswith(f"Addressed {entry['rule']}")
    assert "cancelled" in log["entries"][3]["change"]
    assert "no_show" in log["entries"][3]["change"]


def test_sources_do_not_hardcode_completed_total(tmp_path):
    inbox = tmp_path / "DS-T4-20261112"
    inbox.mkdir()
    shutil.copy(TASK / "generate_appts.py", inbox / "generate_appts.py")
    assert _load_worker().prepare_input(inbox=inbox)["ok"] is True
    rows = load_appointments(inbox / "data" / "appts.csv")
    cents = sum(row["fee_cents"] for row in rows if row["status"] == "completed")
    rendered = f"{cents // 100}.{cents % 100:02d}"
    sources = [
        ROOT / "control_plane" / "appointment_rules.py",
        ROOT / "control_plane" / "contract_verifier.py",
        ROOT / "control_plane" / "reject_revise.py",
        ROOT / "scripts" / "worker_run_task.py",
        TASK / "worker_jobs.py",
        TASK / "TASK.md",
        TASK / "contract.json",
        Path(__file__),
    ]
    for path in sources:
        assert rendered not in path.read_text(encoding="utf-8")


def test_orchestrator_refuses_earlier_task_before_write(tmp_path):
    from control_plane.reject_revise import orchestrate

    inbox = tmp_path / "DS-T1-20261108"
    inbox.mkdir()
    (inbox / "dispatch.json").write_text(
        json.dumps({"task_id": "DS-T1-20261108", "mode": "reject_then_revise", "paid": False, "network": False}),
        encoding="utf-8",
    )
    result = orchestrate(inbox=inbox, repo_root=ROOT)
    assert result["ok"] is False
    assert result["error"] == "refused_task_id"
    assert not (inbox / "deliverables").exists()
    assert not (inbox / "data").exists()


def test_cli_separates_verifier_and_worker(tmp_path):
    inbox = _copy_inbox(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "worker_run_task.py"),
            "--task-id",
            "DS-T4-20261112",
            "--inbox",
            str(inbox),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    summary = json.loads(proc.stdout)
    assert summary["ok"] is True
    assert summary["result"]["verdict_v1"] == "REJECTED"
    assert summary["result"]["verdict_v2"] == "ACCEPTED"
    assert summary["result"]["input_sha256"] == EXPECTED_SHA256
    assert summary["result"]["input_bytes"] == EXPECTED_BYTES
    assert summary["result"]["a6"] == "BLOCKED_PENDING_FOUNDER_API_AUTHORIZATION"

    evidence = json.loads((inbox / "deliverables" / "a4_step_evidence.json").read_text(encoding="utf-8"))
    steps = evidence["steps"]
    assert [step["role"] for step in steps] == ["worker", "verifier", "worker", "verifier"]
    assert [step["step"] for step in steps] == ["prepare_input", "verify_v1", "revise", "verify_v2"]
    assert len({step["pid"] for step in steps}) == 4
    assert evidence["parent_pid"] not in {step["pid"] for step in steps}
    assert all(step["pid"] == step["reported_pid"] for step in steps)
    assert all(step["exit_code"] == 0 for step in steps)
    assert steps[0]["argv"][1].endswith("worker_run_task.py")
    assert steps[1]["argv"][1:3] == ["-m", "control_plane.contract_verifier"]
    assert steps[2]["argv"][1].endswith("worker_run_task.py")
    assert steps[3]["argv"][1:3] == ["-m", "control_plane.contract_verifier"]
    worker_files = set(steps[0]["wrote"] + steps[2]["wrote"])
    verifier_files = set(steps[1]["wrote"] + steps[3]["wrote"])
    assert worker_files.isdisjoint(verifier_files)
    assert "deliverables/verdict_v1.json" in verifier_files
    assert "deliverables/candidate_v2.json" in worker_files

    rows = load_appointments(inbox / "data" / "appts.csv")
    contract = load_contract(inbox / "contract.json")
    v2 = json.loads((inbox / "deliverables" / "candidate_v2.json").read_text(encoding="utf-8"))
    assert v2 == _independent(rows, contract)
    verdict_v2 = json.loads((inbox / "deliverables" / "verdict_v2.json").read_text(encoding="utf-8"))
    assert verdict_v2 == {"verdict": "ACCEPTED", "checks": 4}
    cost = json.loads((inbox / "deliverables" / "cost.json").read_text(encoding="utf-8"))
    assert cost["status"] == "BLOCKED"
    assert cost["completed_paid_run"] is False
    assert cost["paid_api_called"] is False
    assert cost["prompt_tokens"] is None
    assert cost["completion_tokens"] is None
    assert cost["estimated_cny"] is None
    assert cost["calls"] is None
    assert "founder API authorization in the founder chat" in cost["a6"]
    status = json.loads((inbox / "deliverables" / "run_status.json").read_text(encoding="utf-8"))
    assert status["claim"]["production_7x24"] == "NOT_ACCEPTED"
    assert status["claim"]["l2_2_clock"] == "NOT_STARTED"
    assert status["claim"]["observation_track_acceptance"] == "NOT_CLAIMED"
    assert status["paid_api_called"] is False


def test_committed_submission_matches_verifier_and_csv():
    csv_path = TASK / "data" / "appts.csv"
    data = csv_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256
    assert len(data) == EXPECTED_BYTES
    rows = load_appointments(csv_path)
    contract = _contract()
    published = json.loads((TASK / "candidate_v1.json").read_text(encoding="utf-8"))
    verdict_v1 = json.loads((TASK / "deliverables" / "verdict_v1.json").read_text(encoding="utf-8"))
    assert verdict_v1 == judge(published, rows, contract)
    candidate_v2 = json.loads((TASK / "deliverables" / "candidate_v2.json").read_text(encoding="utf-8"))
    assert candidate_v2 == _independent(rows, contract)
    verdict_v2 = json.loads((TASK / "deliverables" / "verdict_v2.json").read_text(encoding="utf-8"))
    assert verdict_v2 == {"verdict": "ACCEPTED", "checks": 4}
    assert verdict_v2 == judge(candidate_v2, rows, contract)
    cost = json.loads((TASK / "deliverables" / "cost.json").read_text(encoding="utf-8"))
    assert cost["status"] == "BLOCKED"
    assert cost["completed_paid_run"] is False
    assert cost["prompt_tokens"] is None
    evidence = json.loads((TASK / "deliverables" / "a4_step_evidence.json").read_text(encoding="utf-8"))
    assert [step["role"] for step in evidence["steps"]] == ["worker", "verifier", "worker", "verifier"]
    assert len({step["pid"] for step in evidence["steps"]}) == 4
    assert evidence["parent_pid"] not in {step["pid"] for step in evidence["steps"]}
    manifest = json.loads((TASK / "deliverables" / "manifest.json").read_text(encoding="utf-8"))
    for rel, meta in manifest["files"].items():
        blob = (TASK / rel).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == meta["sha256"]
        assert len(blob) == meta["bytes"]


def test_cli_stops_when_fingerprint_does_not_match(tmp_path):
    inbox = _copy_inbox(tmp_path)
    generator = inbox / "generate_appts.py"
    generator.write_text(generator.read_text(encoding="utf-8").replace("Random(20261112)", "Random(7)"), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "worker_run_task.py"), "--task-id", "DS-T4-20261112", "--inbox", str(inbox)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode != 0
    assert not (inbox / "deliverables" / "verdict_v2.json").exists()
    cost = json.loads((inbox / "deliverables" / "cost.json").read_text(encoding="utf-8"))
    assert cost["completed_paid_run"] is False
    assert cost["prompt_tokens"] is None
