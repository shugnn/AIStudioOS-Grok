"""Sample public evidence packs. They do not satisfy founder condition 3."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_sha256sums as sums_tool  # noqa: E402
import public_evidence_pack as packmod  # noqa: E402


def _assert_closed(row: dict) -> None:
    assert row["condition_3_satisfied"] is False
    assert row["sample_pack_satisfies_condition_3"] is False
    assert row["dummy_tests_satisfy_condition_3"] is False
    assert row["implementation_satisfies_condition_3"] is False
    assert row["packs_live_soak_evidence"] is False
    assert row["local_only_counts_as_public_evidence"] is False
    assert row["scaffold_sha256sums_is_soak_evidence"] is False
    assert row["can_start_clock"] is False
    assert row["can_accept_l2_2"] is False
    assert row["can_close_l2_2"] is False
    assert row["l2_2_status"] == "NOT_STARTED"
    assert row["clock_state"] == "NOT_STARTED"
    assert row["production_7x24"] == "NOT_ACCEPTED"
    assert row["is_a_start"] is False
    assert row["soak_launched"] is False


def test_sample_public_pack_validates_and_uses_the_scaffold_hasher(tmp_path: Path):
    pack = packmod.sample_public_pack()
    metrics = tmp_path / "final_metrics.json"
    summary = tmp_path / "log_summary.txt"
    metrics.write_bytes(json.dumps(packmod.SAMPLE_METRICS, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    summary.write_bytes(packmod.SAMPLE_LOG_SUMMARY.encode("utf-8"))
    digests = {item["path"]: item["sha256"] for item in pack["sha_list"]}
    assert digests["sample/final_metrics.json"] == sums_tool.sha256_file(metrics)
    assert digests["sample/log_summary.txt"] == sums_tool.sha256_file(summary)
    decision = packmod.validate_pack(pack)
    assert decision["accepted"] is True
    assert decision["rejection"] is None
    assert decision["sample_only"] is True
    assert decision["offline"] is True
    assert decision["missing"] == []
    _assert_closed(decision)


@pytest.mark.parametrize("publication", ["LOCAL_ONLY", "local_only", "local-only", "Local Only"])
def test_local_only_pack_is_refused_and_does_not_count(publication: str):
    pack = packmod.sample_public_pack()
    pack["publication"] = publication
    decision = packmod.validate_pack(pack)
    assert decision["accepted"] is False
    assert decision["rejection"] == "local_only"
    assert decision["local_only_pack_rejected"] is True
    assert decision["sample_only"] is True
    _assert_closed(decision)


@pytest.mark.parametrize(
    ("key", "rejection"),
    [
        ("final_metrics", "missing_final_metrics"),
        ("log_summary", "missing_log_summary"),
        ("sha_list", "missing_sha_list"),
    ],
)
def test_a_pack_missing_one_piece_is_refused(key: str, rejection: str):
    pack = packmod.sample_public_pack()
    pack.pop(key)
    decision = packmod.validate_pack(pack)
    assert decision["accepted"] is False
    assert decision["rejection"] == rejection
    assert decision["missing"] == [key]
    _assert_closed(decision)


def test_scaffold_sha256sums_is_not_soak_evidence():
    sums_path = ROOT / "docs" / "progress" / "l2_2" / "SHA256SUMS.json"
    document = json.loads(sums_path.read_text(encoding="utf-8"))
    document["path"] = "docs/progress/l2_2/SHA256SUMS.json"
    decision = packmod.validate_pack(document)
    assert decision["accepted"] is False
    assert decision["rejection"] == "scaffold_sha256sums_not_soak_evidence"
    _assert_closed(decision)
    assert packmod.committed_scaffold_sums_refused() is True
    dressed = packmod.sample_public_pack()
    dressed["path"] = "docs/progress/l2_2/SHA256SUMS.json"
    dressed["scaffold_sha256sums_is_soak_evidence"] = True
    dressed_decision = packmod.validate_pack(dressed)
    assert dressed_decision["accepted"] is False
    assert dressed_decision["rejection"] == "scaffold_sha256sums_not_soak_evidence"
    assert dressed_decision["scaffold_sha256sums_is_soak_evidence"] is False


def test_sample_exercise_passes_without_satisfying_condition_3():
    status = packmod.stable_scaffold_status()
    assert status["ok"] is True
    assert status["detail"] == "implementation_exists_sample_public_pack_validated"
    assert status["classifies_or_validates_sample_public_pack_passed"] is True
    assert status["local_only_pack_rejected"] is True
    assert status["missing_piece_rejected"] is True
    assert status["scaffold_sha256sums_refused"] is True
    assert status["committed_scaffold_sums_refused"] is True
    assert status["sample_only"] is True
    assert status["offline"] is True
    assert status["tool"] == "scripts/public_evidence_pack.py"
    assert status["hasher"] == "scripts/evidence_sha256sums.py"
    assert status["dut"] == "synthetic_sample_public_pack"
    assert status["scaffold_sha256sums_path"] == "docs/progress/l2_2/SHA256SUMS.json"
    _assert_closed(status)
    assert packmod.scaffold_violations(status) == []
    by_id = {row["id"]: row for row in status["samples"]}
    assert by_id["sample_public_complete"]["accepted"] is True
    assert by_id["local_only_with_all_pieces"]["rejection"] == "local_only"
    assert by_id["missing_final_metrics"]["rejection"] == "missing_final_metrics"
    assert by_id["missing_log_summary"]["rejection"] == "missing_log_summary"
    assert by_id["missing_sha_list"]["rejection"] == "missing_sha_list"
    assert by_id["scaffold_sha256sums"]["rejection"] == "scaffold_sha256sums_not_soak_evidence"
    assert by_id["live_shaped_pack"]["accepted"] is False
    blob = json.dumps(status)
    assert '"condition_3_satisfied": true' not in blob
    assert '"packs_live_soak_evidence": true' not in blob
    assert '"scaffold_sha256sums_is_soak_evidence": true' not in blob
    assert '"can_start_clock": true' not in blob
    forged = json.loads(blob)
    forged["condition_3_satisfied"] = True
    forged["packs_live_soak_evidence"] = True
    forged["local_only_counts_as_public_evidence"] = True
    forged["scaffold_sha256sums_is_soak_evidence"] = True
    forged["can_start_clock"] = True
    forged["l2_2_status"] = "PASS"
    names = set(packmod.scaffold_violations(forged))
    assert "condition_3_unsatisfied" in names
    assert "local_only_refused" in names
    assert "scaffold_sha256sums_not_soak_evidence" in names
    assert "forged_clock_start" in names
    assert "forged_pass" in names


def test_a_pretend_claim_does_not_open_condition_3():
    block = packmod.stable_scaffold_status()
    packmod.annotate_scaffold_claim(
        block,
        {
            "condition_3_satisfied": True,
            "dummy_tests_satisfy_condition_3": True,
            "implementation_satisfies_condition_3": True,
            "packs_live_soak_evidence": True,
            "local_only_counts_as_public_evidence": True,
            "publication": "LOCAL_ONLY",
            "scaffold_sha256sums_is_soak_evidence": True,
            "l2_2_status": "PASS",
            "clock_state": "STARTED",
            "can_start_clock": True,
            "production_7x24": "ACCEPTED",
        },
    )
    packmod.apply_closed_flags(block)
    assert block["sample_pack_claimed_as_condition_3"] is True
    assert block["local_only_called_public_evidence"] is True
    assert block["scaffold_sums_called_soak_evidence"] is True
    assert block["live_soak_pack_claimed"] is True
    assert block["pass_or_start_claimed"] is True
    assert block["classifies_or_validates_sample_public_pack_passed"] is True
    _assert_closed(block)
    assert packmod.scaffold_violations(block) == []


def test_cli_samples_do_not_start_the_clock():
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "public_evidence_pack.py"), "--samples"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["classifies_or_validates_sample_public_pack_passed"] is True
    assert payload["local_only_pack_rejected"] is True
    assert payload["condition_3_satisfied"] is False
    _assert_closed(payload)
    one = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "public_evidence_pack.py"),
            "--pack",
            json.dumps({"publication": "LOCAL_ONLY", "sample_only": True, "offline": True}),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert one.returncode == 0, one.stderr
    rejected = json.loads(one.stdout)
    assert rejected["accepted"] is False
    assert rejected["rejection"] == "local_only"
    assert rejected["local_only_pack_rejected"] is True
    assert rejected["classifies_or_validates_sample_public_pack_passed"] is False
    _assert_closed(rejected)
