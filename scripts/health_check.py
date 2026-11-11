#!/usr/bin/env python3
"""One-shot local health check for AIStudioOS-Grok ($0, no long soak).

Checks: imports, emergency stop module, L1 dry job, CP --once after reset seed=1,
then the L2-2 not-started scaffold (offline preflight + not-started fixture score).
The preflight classifies a synthetic fresh summary and a synthetic stale summary
through the stall watchdog, and reads the committed Ubuntu-24H metrics file only
as a historical SHORT specimen. That specimen is not the 72h gate and not the
stall DUT. Ended SHORT walls are not additive: a sum of 24h walls, including
86400 times 3, is not one continuous 72h soak. Stitching sequential or
restarted soak invocations is not one live process, even back-to-back on the
same host and even when the stitched span reaches 259200. The hook is not a
start and not L2-2 acceptance. The non-additivity gate is not a start. The
process-boundary continuity gate is not a start. The Issue #9 conditional
founder approval is recorded and is not a start. The five start conditions
stay unsatisfied. LOCAL_ONLY is not public evidence. Unknown root cause is
not a terminal attribution. The soak-DUT stall watchdog is not a watchdog of
the supervisor. An offline probe of synthetic supervisor-alive and
supervisor-crash-unrecorded files is not that watchdog either, does not
satisfy founder condition 2, and is not a start. A dummy-process exercise of
scripts/supervisor_watchdog.py can write a crash record within 10 seconds.
That exercise is not a live L2-2 supervisor watchdog, does not demonstrate a
supervision write every 10 minutes, and does not satisfy founder condition 2.
scripts/supervision_cadence.py can write supervision records on a short
time-compressed interval. That exercise does not demonstrate a real
supervision write at least once every 10 minutes, and it does not satisfy
founder condition 2. A write later than 600 seconds does not meet the cadence
bound. scripts/failure_attribution.py classifies sample records into business,
host, or supervision and rejects unknown, empty, missing, free-text, and
multi-class labels. That sample classification does not attribute a live soak
failure and does not satisfy founder condition 4.
scripts/public_evidence_pack.py validates a sample public-shaped pack that
includes final metrics, a log summary, and a SHA list. LOCAL_ONLY is refused
and does not count. A pack missing any of those pieces is refused.
docs/progress/l2_2/SHA256SUMS.json is not live soak evidence. That sample
validation does not satisfy founder condition 3 and is not a start.
Optionally runs the unit suite. That suite is not L2-2 acceptance.

Exit 0 only if all steps ok (and not emergency-stopped).
Exit 0 is overall_ok. It is not a gate PASS, it does not start the 72h clock,
and it does not launch the soak driver.

  py -3 scripts/health_check.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NOT_STARTED_FIXTURE = (
    Path("tests") / "fixtures" / "l2_2" / "scaffold_clock_not_started.json"
)
R2_RELATIVE = Path("docs") / "progress" / "l2_2" / "R2_CHECKLIST.md"
START_DECISION_RELATIVE = Path("docs") / "progress" / "l2_2" / "START_DECISION.md"
GATE_KEYS = ("can_start_clock", "can_accept_l2_2", "can_close_l2_2")
START_DECISIONS = {"given", "started", "approved"}


def step(name: str, ok: bool, detail: str = "", **extra: Any) -> dict:
    row = {"step": name, "ok": ok, "detail": detail, **extra}
    print(json.dumps(row, ensure_ascii=False))
    return row


def interpreter() -> str:
    """The interpreter that launched this process, else python3, else python."""
    exe = sys.executable
    if exe and Path(exe).is_file():
        return exe
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return "python3"


def _add(violations: list[str], name: str) -> None:
    if name not in violations:
        violations.append(name)


def _specimen_view(specimen: Any) -> dict[str, Any]:
    """Honest nested specimen. SHORT only when the preflight row is the committed file.

    clock_state in this view stays NOT_STARTED. The SHORT label is classification.
    """
    closed: dict[str, Any] = {
        "ok": False,
        "role": "historical_short_specimen",
        "path": "docs/progress/soak_2h/metrics.json",
        "experiment": None,
        "sha_short": None,
        "classification": "withheld",
        "wall_elapsed_s": None,
        "max_wall_seconds": None,
        "wall_required_seconds": 259200,
        "below_259200": False,
        "ubuntu_24h_counts_as_72h": False,
        "counts_toward_72h_gate": False,
        "ubuntu_24h_used_as_dut": False,
        "is_stall_dut": False,
        "is_l2_2_acceptance": False,
        "binds_clock_start": False,
        "wrapped_as_started_capture": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "production_7x24": "NOT_ACCEPTED",
        "soak_launched": False,
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
    }
    if not isinstance(specimen, dict):
        return closed
    wall = specimen.get("wall_elapsed_s")
    honest = (
        specimen.get("ok") is True
        and specimen.get("role") == "historical_short_specimen"
        and specimen.get("path") == "docs/progress/soak_2h/metrics.json"
        and specimen.get("classification") == "SHORT"
        and specimen.get("experiment") == "UBUNTU-24H"
        and specimen.get("sha_short") == "aaf8d24"
        and type(wall) is float
        and wall == 86400.001
        and wall < 259200
        and specimen.get("max_wall_seconds") == 86400
        and specimen.get("below_259200") is True
        and specimen.get("wall_required_seconds") == 259200
        and specimen.get("ubuntu_24h_counts_as_72h") is False
        and specimen.get("counts_toward_72h_gate") is False
        and specimen.get("ubuntu_24h_used_as_dut") is False
        and specimen.get("is_stall_dut") is False
        and specimen.get("is_l2_2_acceptance") is False
        and specimen.get("binds_clock_start") is False
        and specimen.get("wrapped_as_started_capture") is False
        and specimen.get("l2_2_status") == "NOT_STARTED"
        and specimen.get("clock_state") == "NOT_STARTED"
        and specimen.get("clock_effect") == "none"
        and specimen.get("production_7x24") == "NOT_ACCEPTED"
        and specimen.get("soak_launched") is False
        and all(specimen.get(key) is False for key in GATE_KEYS)
    )
    if not honest:
        return closed
    viewed = dict(closed)
    viewed["ok"] = True
    viewed["experiment"] = "UBUNTU-24H"
    viewed["sha_short"] = "aaf8d24"
    viewed["classification"] = "SHORT"
    viewed["wall_elapsed_s"] = 86400.001
    viewed["max_wall_seconds"] = 86400
    viewed["below_259200"] = True
    return viewed


def _note_specimen(specimen: Any, violations: list[str]) -> dict[str, Any]:
    """Fail closed when a report treats Ubuntu-24H as 72h, PASS, a start, or the DUT."""
    if not isinstance(specimen, dict):
        _add(violations, "ubuntu_24h_specimen")
        return _specimen_view(None)
    if specimen.get("ubuntu_24h_counts_as_72h") is True or specimen.get("counts_toward_72h_gate") is True:
        _add(violations, "ubuntu_24h_as_72h")
    if specimen.get("below_259200") is False and specimen.get("classification") == "SHORT":
        _add(violations, "ubuntu_24h_as_72h")
    wall = specimen.get("wall_elapsed_s")
    if isinstance(wall, (int, float)) and not isinstance(wall, bool) and float(wall) >= 259200:
        _add(violations, "ubuntu_24h_as_72h")
    classification = specimen.get("classification")
    if classification in {"72h", "72H", "WALL_OBSERVED"}:
        _add(violations, "ubuntu_24h_as_72h")
    if classification == "PASS":
        _add(violations, "forged_pass")
    if classification == "ACCEPTED":
        _add(violations, "forged_production_accepted")
    if classification in {"STARTED", "started"}:
        _add(violations, "forged_clock_start")
    if specimen.get("ubuntu_24h_used_as_dut") is True or specimen.get("is_stall_dut") is True:
        _add(violations, "ubuntu_24h_as_dut")
    if specimen.get("is_l2_2_acceptance") is True:
        _add(violations, "ubuntu_24h_as_acceptance")
    if specimen.get("binds_clock_start") is True or specimen.get("wrapped_as_started_capture") is True:
        _add(violations, "ubuntu_24h_as_start")
    if specimen.get("can_start_clock") is True:
        _add(violations, "forged_can_start_clock")
    if specimen.get("l2_2_status") == "PASS":
        _add(violations, "forged_pass")
    if specimen.get("clock_state") not in {None, "NOT_STARTED"}:
        _add(violations, "forged_clock_start")
    if specimen.get("production_7x24") not in {None, "NOT_ACCEPTED"}:
        _add(violations, "forged_production_accepted")
    viewed = _specimen_view(specimen)
    if viewed["classification"] != "SHORT":
        _add(violations, "ubuntu_24h_specimen")
    return viewed


def _l2_modules() -> tuple[Any, Any]:
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import l2_2_preflight as preflight_mod
    import l2_2_score as score_mod

    return preflight_mod, score_mod


def _walk_claims(node: Any, violations: list[str]) -> None:
    """Fail closed on a nested PASS, ACCEPTED, start, or open gate.

    Honest reports mention those words inside refusal sentences. This walk
    reads claim fields only.
    """
    if isinstance(node, dict):
        if "l2_2_status" in node:
            status = node.get("l2_2_status")
            if not isinstance(status, str):
                _add(violations, "l2_2_status")
            else:
                upper = status.strip().upper().replace(" ", "_")
                if upper == "PASS" or upper.startswith("PASS"):
                    _add(violations, "forged_pass")
                elif upper == "ACCEPTED":
                    _add(violations, "forged_accept_status")
                elif upper != "NOT_STARTED":
                    _add(violations, "l2_2_status")
        if "clock_state" in node and node.get("clock_state") != "NOT_STARTED":
            _add(violations, "forged_clock_start")
        if node.get("clock_started") is True:
            _add(violations, "forged_clock_start")
        if "clock_effect" in node and node.get("clock_effect") != "none":
            _add(violations, "forged_clock_start")
        if node.get("soak_launched") is True or node.get("documented_soak_argv_executed") is True:
            _add(violations, "soak_launched")
        if "production_7x24" in node and node.get("production_7x24") != "NOT_ACCEPTED":
            _add(violations, "forged_production_accepted")
        if node.get("exit_0_is_gate_pass") is True or node.get("gate_result") == "PASS":
            _add(violations, "forged_pass")
        if node.get("verified") is True or node.get("supervision_verified") is True:
            _add(violations, "verified_claim")
        decision = node.get("start_decision")
        if isinstance(decision, str) and decision.strip().lower() in START_DECISIONS:
            _add(violations, "forged_start_decision")
        if node.get("approval_is_a_start") is True or node.get("approval_is_a_pass") is True:
            _add(violations, "approval_is_not_a_start")
        if node.get("approval_without_conditions_is_a_start") is True:
            _add(violations, "approval_is_not_a_start")
        if node.get("approval_without_start_registration_is_a_start") is True:
            _add(violations, "approval_is_not_a_start")
        if node.get("start_registration_present") is True or node.get("start_registration_posted_to_issue_9") is True:
            _add(violations, "approval_is_not_a_start")
        if node.get("conditions_satisfied") is True:
            _add(violations, "founder_conditions_missing")
        if node.get("local_only_counts_as_public_evidence") is True:
            _add(violations, "local_only_refused")
        if node.get("unknown_root_cause_allowed") is True:
            _add(violations, "unknown_root_cause_refused")
        if node.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is True:
            _add(violations, "supervisor_watchdog_required")
        if node.get("soak_dut_stall_watchdog_is_supervisor_watchdog") is True:
            _add(violations, "supervisor_watchdog_required")
        if node.get("condition_2_satisfied") is True or node.get("offline_probe_satisfies_condition_2") is True:
            _add(violations, "condition_2_unsatisfied")
        if (
            node.get("dummy_tests_satisfy_condition_2") is True
            or node.get("scaffold_satisfies_condition_2") is True
            or node.get("implementation_satisfies_condition_2") is True
            or node.get("synthetic_probe_satisfies_condition_2") is True
            or node.get("stall_watchdog_satisfies_condition_2") is True
            or node.get("dummy_crash_within_10s_satisfies_condition_2") is True
            or node.get("demonstrates_10_minute_supervision_cadence") is True
            or node.get("record_11s_later_meets_requirement") is True
            or node.get("time_compressed_exercise_satisfies_condition_2") is True
            or node.get("offline_exercise_satisfies_condition_2") is True
            or node.get("time_compressed_exercise_demonstrates_10_minute_cadence") is True
            or node.get("writes_on_schedule_demonstrate_10_minute_cadence") is True
            or node.get("bound_gap_demonstrates_10_minute_supervision_cadence") is True
        ):
            _add(violations, "condition_2_unsatisfied")
        if (
            node.get("stall_watchdog_is_cadence_writer") is True
            or node.get("supervisor_watchdog_is_cadence_writer") is True
            or node.get("is_live_l2_2_supervisor") is True
        ):
            _add(violations, "supervision_cadence_writer")
        if (
            node.get("offline_probe_is_supervisor_watchdog") is True
            or node.get("is_supervisor_watchdog_of_live_supervisor") is True
            or node.get("is_live_l2_2_supervisor_watchdog") is True
            or node.get("live_supervisor_process") is True
            or node.get("live_watchdog_process") is True
        ):
            _add(violations, "offline_probe_is_not_supervisor_watchdog")
        if node.get("offline_probe_is_a_start") is True or node.get("is_a_start") is True:
            _add(violations, "offline_probe_is_not_a_start")
        if (
            node.get("condition_4_satisfied") is True
            or node.get("sample_classification_satisfies_condition_4") is True
            or node.get("dummy_tests_satisfy_condition_4") is True
            or node.get("implementation_satisfies_condition_4") is True
            or node.get("attributes_live_soak_failure") is True
        ):
            _add(violations, "condition_4_unsatisfied")
        if (
            node.get("condition_3_satisfied") is True
            or node.get("sample_pack_satisfies_condition_3") is True
            or node.get("dummy_tests_satisfy_condition_3") is True
            or node.get("implementation_satisfies_condition_3") is True
            or node.get("packs_live_soak_evidence") is True
        ):
            _add(violations, "condition_3_unsatisfied")
        if node.get("scaffold_sha256sums_is_soak_evidence") is True:
            _add(violations, "scaffold_sha256sums_not_soak_evidence")
        if node.get("a_72h_pass_is_production_readiness") is True:
            _add(violations, "forged_production_accepted")
        for key in GATE_KEYS:
            if node.get(key) is True:
                _add(violations, "forged_" + key)
        for value in node.values():
            _walk_claims(value, violations)
    elif isinstance(node, list):
        for item in node:
            _walk_claims(item, violations)


def _supervisor_row_ok(row: Any, *, claims_required: bool = True) -> bool:
    """True when a supervisor-watchdog row stays an offline hole, not a start."""
    if not isinstance(row, dict):
        return False
    if (
        row.get("ok") is not True
        or row.get("detail") != "synthetic_alive_vs_crash_unrecorded"
        or row.get("action") != "synthetic_supervisor_files"
        or row.get("dut") != "synthetic_temp_supervisor"
        or row.get("tool") != "scripts/l2_2_score.py"
        or row.get("soak_dut_watchdog_tool") != "scripts/stall_watchdog.py"
        or row.get("condition_2_satisfied") is not False
        or row.get("offline_probe_satisfies_condition_2") is not False
        or row.get("offline_probe_is_supervisor_watchdog") is not False
        or row.get("offline_probe_is_a_start") is not False
        or row.get("is_supervisor_watchdog_of_live_supervisor") is not False
        or row.get("soak_dut_stall_watchdog_is_supervisor_watchdog") is not False
        or row.get("is_a_start") is not False
        or row.get("live_supervisor_process") is not False
        or row.get("live_soak_process") is not False
        or row.get("soak_launched") is not False
        or row.get("l2_2_status") != "NOT_STARTED"
        or row.get("clock_state") != "NOT_STARTED"
        or row.get("clock_effect") != "none"
        or row.get("production_7x24") != "NOT_ACCEPTED"
        or any(row.get(key) is not False for key in GATE_KEYS)
    ):
        return False
    cases = row.get("cases")
    if not isinstance(cases, list):
        return False
    labels = [item.get("label") if isinstance(item, dict) else None for item in cases]
    classes = [item.get("classification") if isinstance(item, dict) else None for item in cases]
    if labels != ["supervisor_alive", "supervisor_crash_unrecorded", "supervisor_crash_record_too_slow"]:
        return False
    if classes != ["supervisor_alive", "supervisor_crash_unrecorded", "supervisor_crash_unrecorded"]:
        return False
    for item in cases:
        if (
            item.get("condition_2_satisfied") is not False
            or item.get("live_process") is not False
            or item.get("counts_as_supervisor_watchdog") is not False
            or item.get("is_a_start") is not False
            or item.get("l2_2_status") != "NOT_STARTED"
        ):
            return False
    if claims_required:
        claims = row.get("refused_claims")
        if not isinstance(claims, list):
            return False
        claim_labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if claim_labels != [
            "soak_dut_stall_watchdog_substituted",
            "offline_probe_substituted",
            "condition_2_and_pass_claimed",
        ]:
            return False
    elif (
        row.get("stall_watchdog_claimed_as_supervisor_watchdog") is not False
        or row.get("offline_probe_claimed_as_supervisor_watchdog") is not False
        or row.get("condition_2_claimed_satisfied") is not False
        or row.get("pass_or_start_claimed") is not False
    ):
        return False
    note = str(row.get("note") or "")
    if "does not satisfy founder condition 2" not in note or "not a start" not in note:
        return False
    return True


def _dummy_exercise_passed(preflight_report: Any, score_report: Any) -> bool:
    """True only when both reports record a closed dummy exercise that passed."""

    def row_ok(row: Any) -> bool:
        return (
            isinstance(row, dict)
            and row.get("ok") is True
            and row.get("dummy_crash_within_10s_passed") is True
            and row.get("dummy_still_alive_wrote_no_crash_record") is True
            and row.get("record_11s_later_meets_requirement") is False
            and row.get("condition_2_satisfied") is False
            and row.get("dummy_tests_satisfy_condition_2") is False
            and row.get("implementation_satisfies_condition_2") is False
            and row.get("demonstrates_10_minute_supervision_cadence") is False
            and row.get("l2_2_status") == "NOT_STARTED"
            and row.get("clock_state") == "NOT_STARTED"
            and row.get("can_start_clock") is False
        )

    if not isinstance(preflight_report, dict) or not isinstance(score_report, dict):
        return False
    return row_ok(preflight_report.get("supervisor_watchdog_implementation")) and row_ok(
        score_report.get("supervisor_watchdog_implementation")
    )


def _cadence_exercise_passed(preflight_report: Any, score_report: Any) -> bool:
    """True only when both reports record a closed short-interval exercise that passed."""

    def row_ok(row: Any) -> bool:
        return (
            isinstance(row, dict)
            and row.get("ok") is True
            and row.get("writes_on_schedule_passed") is True
            and row.get("time_compressed") is True
            and row.get("simulated_clock") is False
            and row.get("late_write_meets_cadence") is False
            and row.get("production_max_seconds") == 600
            and row.get("condition_2_satisfied") is False
            and row.get("demonstrates_10_minute_supervision_cadence") is False
            and row.get("is_supervisor_watchdog_of_live_supervisor") is False
            and row.get("l2_2_status") == "NOT_STARTED"
            and row.get("clock_state") == "NOT_STARTED"
            and row.get("can_start_clock") is False
            and row.get("production_7x24") == "NOT_ACCEPTED"
        )

    if not isinstance(preflight_report, dict) or not isinstance(score_report, dict):
        return False
    return row_ok(preflight_report.get("supervision_cadence_writer")) and row_ok(
        score_report.get("supervision_cadence_writer")
    )


def _attribution_exercise_passed(preflight_report: Any, score_report: Any) -> bool:
    """True only when both reports record a closed sample classification that passed."""

    def row_ok(row: Any) -> bool:
        return (
            isinstance(row, dict)
            and row.get("ok") is True
            and row.get("classifies_sample_attributions_passed") is True
            and row.get("unknown_root_cause_rejected") is True
            and row.get("condition_4_satisfied") is False
            and row.get("attributes_live_soak_failure") is False
            and row.get("dummy_tests_satisfy_condition_4") is False
            and row.get("implementation_satisfies_condition_4") is False
            and row.get("condition_2_satisfied") is False
            and row.get("demonstrates_10_minute_supervision_cadence") is False
            and row.get("is_supervisor_watchdog_of_live_supervisor") is False
            and row.get("l2_2_status") == "NOT_STARTED"
            and row.get("clock_state") == "NOT_STARTED"
            and row.get("can_start_clock") is False
            and row.get("production_7x24") == "NOT_ACCEPTED"
        )

    if not isinstance(preflight_report, dict) or not isinstance(score_report, dict):
        return False
    return row_ok(preflight_report.get("failure_attribution")) and row_ok(score_report.get("failure_attribution"))


def _pack_exercise_passed(preflight_report: Any, score_report: Any) -> bool:
    """True only when both reports record a closed sample pack validation that passed."""

    def row_ok(row: Any) -> bool:
        return (
            isinstance(row, dict)
            and row.get("ok") is True
            and row.get("sample_only") is True
            and row.get("offline") is True
            and row.get("classifies_or_validates_sample_public_pack_passed") is True
            and row.get("local_only_pack_rejected") is True
            and row.get("missing_piece_rejected") is True
            and row.get("scaffold_sha256sums_refused") is True
            and row.get("condition_3_satisfied") is False
            and row.get("packs_live_soak_evidence") is False
            and row.get("dummy_tests_satisfy_condition_3") is False
            and row.get("implementation_satisfies_condition_3") is False
            and row.get("local_only_counts_as_public_evidence") is False
            and row.get("scaffold_sha256sums_is_soak_evidence") is False
            and row.get("l2_2_status") == "NOT_STARTED"
            and row.get("clock_state") == "NOT_STARTED"
            and row.get("can_start_clock") is False
            and row.get("production_7x24") == "NOT_ACCEPTED"
        )

    if not isinstance(preflight_report, dict) or not isinstance(score_report, dict):
        return False
    return row_ok(preflight_report.get("public_evidence_pack")) and row_ok(score_report.get("public_evidence_pack"))


def _pack_row_ok(row: Any) -> bool:
    """True when the sample public-pack scaffold stays closed and the exercise passed."""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import public_evidence_pack as evidence_pack
    except Exception:
        return False
    return evidence_pack.scaffold_violations(row, require_success=True) == []


def _attribution_row_ok(row: Any) -> bool:
    """True when the sample attribution scaffold stays closed and the exercise passed."""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import failure_attribution as attribution
    except Exception:
        return False
    return attribution.scaffold_violations(row, require_success=True) == []


def _cadence_row_ok(row: Any) -> bool:
    """True when the short cadence scaffold stays closed and the exercise passed."""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import supervision_cadence as cadence
    except Exception:
        return False
    return cadence.scaffold_violations(row, require_success=True) == []


def _implementation_row_ok(row: Any) -> bool:
    """True when the dummy watchdog scaffold stays closed and the exercise passed."""
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import supervisor_watchdog as watchdog
    except Exception:
        return False
    return watchdog.scaffold_violations(row, require_success=True) == []


def l2_2_commands(root: Path | None = None) -> list[list[str]]:
    """Offline preflight and the not-started fixture score. No soak driver."""
    repo = root or ROOT
    exe = interpreter()
    return [
        [exe, str(repo / "scripts" / "l2_2_preflight.py")],
        [
            exe,
            str(repo / "scripts" / "l2_2_score.py"),
            "--capture",
            str(repo / NOT_STARTED_FIXTURE),
        ],
    ]


def pytest_command() -> list[str]:
    return [interpreter(), "-m", "pytest", "tests/", "-q"]


def _run_json(cmd: list[str]) -> tuple[int, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, {"ok": False, "error": type(exc).__name__}
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode if proc.returncode else 1, None


def _read_repo_text(root: Path, relative: Path) -> str:
    path = root / relative
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def assess_l2_2_offline(
    preflight_report: Any,
    score_report: Any,
    *,
    r2_text: str,
    preflight_exit: int,
    score_exit: int,
    start_decision_text: str | None = None,
) -> dict[str, Any]:
    """Honest NOT_STARTED check. Gates in the result stay false.

    A scorer exit 0 on a started or INCOMPLETE bundle is not acceptance.
    Filling START_DECISION.md is not a start. A forged claim in that file
    fails this check and does not open can_start_clock.
    """
    violations: list[str] = []
    r2_unfilled = False
    start_decision_unfilled = False
    specimen_view = _specimen_view(None)
    if start_decision_text is None:
        start_decision_text = _read_repo_text(ROOT, START_DECISION_RELATIVE)
    try:
        preflight_mod, score_mod = _l2_modules()
    except Exception as exc:
        _add(violations, "l2_import:" + type(exc).__name__)
        preflight_mod = None
        score_mod = None

    if preflight_exit != 0:
        _add(violations, "preflight_exit")
    if score_exit != 0:
        _add(violations, "score_exit")
    if not isinstance(preflight_report, dict):
        _add(violations, "preflight_unreadable")
    if not isinstance(score_report, dict):
        _add(violations, "score_unreadable")

    if preflight_mod is not None and isinstance(preflight_report, dict):
        if preflight_report.get("schema") != preflight_mod.SCHEMA:
            _add(violations, "preflight_schema")
        if preflight_report.get("report_kind") != "offline_preflight":
            _add(violations, "preflight_kind")
        if preflight_report.get("soak_launched") is not False:
            _add(violations, "soak_launched")
        if preflight_report.get("documented_soak_argv_executed") is not False:
            _add(violations, "soak_launched")
        if preflight_report.get("not_started_scaffold_intact") is not True:
            _add(violations, "scaffold_not_intact")
        source = preflight_report.get("source") if isinstance(preflight_report.get("source"), dict) else {}
        if source.get("collector_mode") != "offline_preflight":
            _add(violations, "preflight_not_offline")
        checks = preflight_report.get("checks") if isinstance(preflight_report.get("checks"), dict) else {}
        flags = checks.get("soak_flags") if isinstance(checks.get("soak_flags"), dict) else {}
        if flags.get("executed") is not False:
            _add(violations, "soak_launched")
        r2_row = checks.get("r2_checklist") if isinstance(checks.get("r2_checklist"), dict) else {}
        report_unfilled = r2_row.get("unfilled") is True and r2_row.get("start_decision") == "not_given"
        if not report_unfilled:
            _add(violations, "r2_report_not_blank")
        sd_row = checks.get("start_decision") if isinstance(checks.get("start_decision"), dict) else {}
        report_sd_unfilled = (
            sd_row.get("unfilled") is True
            and sd_row.get("start_decision") == "not_given"
            and sd_row.get("ok") is True
        )
        if not report_sd_unfilled:
            _add(violations, "start_decision_report_not_blank")
        if sd_row.get("detail") == "forged_claim" or sd_row.get("binds_clock_start") is True:
            _add(violations, "start_decision_forged")
        for name in preflight_mod.validate_report(preflight_report):
            if name in {"forged_can_start_clock", "forged_can_accept_l2_2", "forged_can_close_l2_2"}:
                _add(violations, name)
            elif name == "status":
                _add(violations, "l2_2_status")
            elif name == "clock_state":
                _add(violations, "forged_clock_start")
            elif name == "soak_launched":
                _add(violations, "soak_launched")
            elif name == "production_claim":
                _add(violations, "forged_production_accepted")
            elif name in {"exit_0_claim", "gate_result"}:
                _add(violations, "forged_pass")
            elif name in {"r2_implies_start", "start_decision_implies_start"}:
                _add(violations, "forged_start_decision")
            elif name in {
                "stall_implies_start",
                "stall_ubuntu_dut",
                "stall_alert_in_repo",
                "stall_classification",
                "stall_gap_appended",
                "stall_watchdog",
                "ubuntu_24h_as_72h",
                "ubuntu_24h_as_dut",
                "ubuntu_24h_as_acceptance",
                "ubuntu_24h_as_start",
                "ubuntu_24h_specimen",
                "ubuntu_24h_specimen_mismatch",
                "additive_historical_shorts",
                "additive_as_start",
                "non_additivity",
                "non_additivity_mismatch",
                "stitched_process_boundaries",
                "stitch_as_start",
                "process_continuity",
                "process_continuity_mismatch",
                "founder_start_conditions",
                "founder_start_conditions_mismatch",
                "founder_conditions_missing",
                "approval_is_not_a_start",
                "local_only_refused",
                "unknown_root_cause_refused",
                "supervisor_watchdog_required",
                "supervisor_watchdog_honesty",
                "supervisor_watchdog_honesty_mismatch",
                "supervisor_watchdog_implementation",
                "supervisor_watchdog_implementation_mismatch",
                "supervision_cadence_writer",
                "supervision_cadence_writer_mismatch",
                "failure_attribution",
                "failure_attribution_mismatch",
                "public_evidence_pack",
                "public_evidence_pack_mismatch",
                "condition_4_unsatisfied",
                "condition_3_unsatisfied",
                "scaffold_sha256sums_not_soak_evidence",
                "condition_2_unsatisfied",
                "offline_probe_is_not_supervisor_watchdog",
                "offline_probe_is_not_a_start",
            }:
                _add(violations, name)
            else:
                _add(violations, "preflight:" + name)
        _walk_claims(preflight_report, violations)
        stall = checks.get("stall_watchdog") if isinstance(checks.get("stall_watchdog"), dict) else {}
        if stall.get("ok") is not True or stall.get("detail") != "synthetic_fresh_vs_stale":
            _add(violations, "stall_watchdog")
        if stall.get("action") != "synthetic_mtime" or stall.get("dut") != "synthetic_temp_summary":
            _add(violations, "stall_not_synthetic")
        if stall.get("ubuntu_24h_used_as_dut") is not False or stall.get("default_summary_used") is not False:
            _add(violations, "stall_ubuntu_dut")
        if (
            stall.get("fresh_stalled") is not False
            or stall.get("stale_stalled") is not True
            or stall.get("fresh_exit") != 0
            or stall.get("stale_exit") != 1
            or stall.get("fresh_gap_band") != "ok"
            or stall.get("stale_gap_band") != "red"
            or stall.get("gap_appended") is not False
        ):
            _add(violations, "stall_classification")
        if (
            stall.get("binds_clock_start") is True
            or stall.get("implies_l2_2_acceptance") is True
            or stall.get("implies_72h_pass") is True
            or stall.get("gap_implies_soak_complete") is True
        ):
            _add(violations, "stall_implies_start")
        if stall.get("clock_effect") != "none" or stall.get("clock_state") != "NOT_STARTED":
            _add(violations, "forged_clock_start")
        if stall.get("l2_2_status") != "NOT_STARTED":
            _add(violations, "l2_2_status")
        if stall.get("soak_launched") is not False:
            _add(violations, "soak_launched")
        if stall.get("repo_alert_written") is True or stall.get("alert_left_in_repo") is True:
            _add(violations, "stall_alert_in_repo")
        if stall.get("production_7x24") != "NOT_ACCEPTED":
            _add(violations, "forged_production_accepted")
        for key in GATE_KEYS:
            if stall.get(key) is True:
                _add(violations, "forged_" + key)
        checks_specimen = checks.get("ubuntu_24h_specimen")
        top_specimen = preflight_report.get("ubuntu_24h_specimen")
        if checks_specimen != top_specimen:
            _add(violations, "ubuntu_24h_specimen_mismatch")
        checked_specimen = _note_specimen(checks_specimen, violations)
        _note_specimen(top_specimen, violations)
        if checks_specimen == top_specimen and checked_specimen["classification"] == "SHORT":
            specimen_view = checked_specimen
        additive = checks.get("non_additivity")
        top_additive = preflight_report.get("non_additivity")
        if additive != top_additive:
            _add(violations, "non_additivity_mismatch")
        if (
            not isinstance(additive, dict)
            or additive.get("ok") is not True
            or additive.get("detail") != "shorts_not_additive"
            or additive.get("rule") != "one_continuous_monotonic_wall"
            or additive.get("historical_shorts_are_additive") is not False
            or additive.get("sum_of_shorts_counts_toward_gate") is not False
            or additive.get("d1_windows_bound_as_specimen") is not False
            or additive.get("d1_windows_metrics_file") is not None
            or additive.get("l2_2_status") != "NOT_STARTED"
            or additive.get("clock_state") != "NOT_STARTED"
            or additive.get("clock_effect") != "none"
            or additive.get("soak_launched") is not False
            or additive.get("documented_soak_argv_executed") is not False
            or additive.get("production_7x24") != "NOT_ACCEPTED"
            or any(additive.get(key) is not False for key in GATE_KEYS)
        ):
            _add(violations, "non_additivity")
        sums = additive.get("refused_sums") if isinstance(additive, dict) else None
        if not isinstance(sums, list) or not sums:
            _add(violations, "non_additivity")
        else:
            for item in sums:
                if not isinstance(item, dict):
                    _add(violations, "additive_historical_shorts")
                    continue
                if item.get("counts_toward_gate") is not False or item.get("historical_shorts_are_additive") is not False:
                    _add(violations, "additive_historical_shorts")
                if item.get("continuous_monotonic_wall") is not False or item.get("single_live_soak") is not False:
                    _add(violations, "additive_historical_shorts")
                if item.get("naive_sum_reaches_259200") is True and item.get("counts_toward_gate") is not False:
                    _add(violations, "additive_historical_shorts")
        continuity = checks.get("process_continuity")
        top_continuity = preflight_report.get("process_continuity")
        if continuity != top_continuity:
            _add(violations, "process_continuity_mismatch")
        if (
            not isinstance(continuity, dict)
            or continuity.get("ok") is not True
            or continuity.get("detail") != "stitches_not_continuous"
            or continuity.get("rule") != "one_live_soak_process"
            or continuity.get("sequential_soaks_are_continuous") is not False
            or continuity.get("stitched_processes_count_toward_gate") is not False
            or continuity.get("counts_toward_gate") is not False
            or continuity.get("d1_windows_bound_as_specimen") is not False
            or continuity.get("d1_windows_metrics_file") is not None
            or continuity.get("l2_2_status") != "NOT_STARTED"
            or continuity.get("clock_state") != "NOT_STARTED"
            or continuity.get("clock_effect") != "none"
            or continuity.get("soak_launched") is not False
            or continuity.get("documented_soak_argv_executed") is not False
            or continuity.get("production_7x24") != "NOT_ACCEPTED"
            or any(continuity.get(key) is not False for key in GATE_KEYS)
        ):
            _add(violations, "process_continuity")
        stitches = continuity.get("refused_stitches") if isinstance(continuity, dict) else None
        if not isinstance(stitches, list) or not stitches:
            _add(violations, "process_continuity")
        else:
            for item in stitches:
                if not isinstance(item, dict):
                    _add(violations, "stitched_process_boundaries")
                    continue
                if (
                    item.get("counts_toward_gate") is not False
                    or item.get("sequential_soaks_are_continuous") is not False
                    or item.get("stitched_processes_count_toward_gate") is not False
                    or item.get("single_live_process") is not False
                ):
                    _add(violations, "stitched_process_boundaries")
                reaches = (
                    item.get("stitched_duration_reaches_259200") is True
                    or item.get("calendar_span_reaches_259200") is True
                )
                if reaches and item.get("counts_toward_gate") is not False:
                    _add(violations, "stitched_process_boundaries")
        founder = checks.get("founder_start_conditions")
        top_founder = preflight_report.get("founder_start_conditions")
        if founder != top_founder:
            _add(violations, "founder_start_conditions_mismatch")
        if (
            not isinstance(founder, dict)
            or founder.get("ok") is not True
            or founder.get("detail") != "approval_recorded_not_a_start"
            or founder.get("rule") != "five_founder_conditions_before_start"
            or founder.get("approval_exists") is not True
            or founder.get("approval_conditional") is not True
            or founder.get("approval_comment_id") != 6761044915
            or founder.get("approval_utc") != "2026-11-10T06:50:14Z"
            or founder.get("approval_is_a_start") is not False
            or founder.get("approval_is_a_pass") is not False
            or founder.get("conditions_satisfied") is not False
            or founder.get("start_registration_present") is not False
            or founder.get("start_registration_posted_to_issue_9") is not False
            or founder.get("templates_unfilled") is not True
            or founder.get("local_only_counts_as_public_evidence") is not False
            or founder.get("unknown_root_cause_allowed") is not False
            or founder.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is not False
            or founder.get("a_72h_pass_is_production_readiness") is not False
            or founder.get("declarations_are_not_a_start") is not True
            or founder.get("l2_2_status") != "NOT_STARTED"
            or founder.get("clock_state") != "NOT_STARTED"
            or founder.get("clock_effect") != "none"
            or founder.get("soak_launched") is not False
            or founder.get("production_7x24") != "NOT_ACCEPTED"
            or any(founder.get(key) is not False for key in GATE_KEYS)
        ):
            _add(violations, "founder_start_conditions")
        claims = founder.get("refused_claims") if isinstance(founder, dict) else None
        if not isinstance(claims, list) or not claims:
            _add(violations, "founder_start_conditions")
        else:
            for item in claims:
                if not isinstance(item, dict):
                    _add(violations, "founder_conditions_missing")
                    continue
                if item.get("conditions_satisfied") is not False or item.get("approval_is_a_start") is not False:
                    _add(violations, "founder_conditions_missing")
                if item.get("counts_as_start") is not False or item.get("can_start_clock") is not False:
                    _add(violations, "approval_is_not_a_start")
                if item.get("local_only_counts_as_public_evidence") is not False:
                    _add(violations, "local_only_refused")
                if item.get("unknown_root_cause_allowed") is not False:
                    _add(violations, "unknown_root_cause_refused")
                if item.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is not False:
                    _add(violations, "supervisor_watchdog_required")
        watchdog = checks.get("supervisor_watchdog_honesty")
        top_watchdog = preflight_report.get("supervisor_watchdog_honesty")
        if watchdog != top_watchdog:
            _add(violations, "supervisor_watchdog_honesty_mismatch")
        if not _supervisor_row_ok(watchdog):
            _add(violations, "supervisor_watchdog_honesty")
        claim_rows = watchdog.get("refused_claims") if isinstance(watchdog, dict) else None
        if not isinstance(claim_rows, list) or not claim_rows:
            _add(violations, "supervisor_watchdog_honesty")
        else:
            for item in claim_rows:
                if not isinstance(item, dict):
                    _add(violations, "condition_2_unsatisfied")
                    continue
                if item.get("condition_2_satisfied") is not False or item.get("offline_probe_satisfies_condition_2") is not False:
                    _add(violations, "condition_2_unsatisfied")
                if item.get("offline_probe_is_supervisor_watchdog") is not False or item.get("is_a_start") is not False:
                    _add(violations, "offline_probe_is_not_supervisor_watchdog")
                if item.get("soak_dut_stall_watchdog_is_supervisor_watchdog") is not False:
                    _add(violations, "supervisor_watchdog_required")
                if item.get("can_start_clock") is not False or item.get("l2_2_status") != "NOT_STARTED":
                    _add(violations, "offline_probe_is_not_a_start")
                if item.get("production_7x24") != "NOT_ACCEPTED":
                    _add(violations, "forged_production_accepted")
        implementation = checks.get("supervisor_watchdog_implementation")
        top_implementation = preflight_report.get("supervisor_watchdog_implementation")
        if implementation != top_implementation:
            _add(violations, "supervisor_watchdog_implementation_mismatch")
        if not _implementation_row_ok(implementation):
            _add(violations, "supervisor_watchdog_implementation")
        cadence = checks.get("supervision_cadence_writer")
        top_cadence = preflight_report.get("supervision_cadence_writer")
        if cadence != top_cadence:
            _add(violations, "supervision_cadence_writer_mismatch")
        if not _cadence_row_ok(cadence):
            _add(violations, "supervision_cadence_writer")
        attribution = checks.get("failure_attribution")
        top_attribution = preflight_report.get("failure_attribution")
        if attribution != top_attribution:
            _add(violations, "failure_attribution_mismatch")
        if not _attribution_row_ok(attribution):
            _add(violations, "failure_attribution")
        evidence_pack = checks.get("public_evidence_pack")
        top_evidence_pack = preflight_report.get("public_evidence_pack")
        if evidence_pack != top_evidence_pack:
            _add(violations, "public_evidence_pack_mismatch")
        if not _pack_row_ok(evidence_pack):
            _add(violations, "public_evidence_pack")

    if score_mod is not None and isinstance(score_report, dict):
        if score_report.get("schema") != score_mod.SCHEMA_REPORT:
            _add(violations, "score_schema")
        if score_report.get("l2_2_status") != "NOT_STARTED":
            if score_report.get("l2_2_status") == "PASS":
                _add(violations, "forged_pass")
            else:
                _add(violations, "l2_2_status")
        if score_report.get("clock_state") != "NOT_STARTED":
            _add(violations, "forged_clock_start")
        source = score_report.get("source") if isinstance(score_report.get("source"), dict) else {}
        if source.get("collector_mode") != "offline_score":
            _add(violations, "score_not_offline")
        if source.get("synthetic") is not True:
            _add(violations, "not_scaffold_fixture")
        block = score_report.get("non_additivity")
        if not isinstance(block, dict):
            _add(violations, "non_additivity")
        else:
            if (
                block.get("historical_shorts_are_additive") is not False
                or block.get("sum_of_shorts_counts_toward_gate") is not False
                or block.get("counts_toward_gate") is not False
                or block.get("additive_claim") is not False
                or block.get("rule") != "one_continuous_monotonic_wall"
            ):
                _add(violations, "additive_historical_shorts")
        continuity = score_report.get("process_continuity")
        if not isinstance(continuity, dict):
            _add(violations, "process_continuity")
        else:
            if (
                continuity.get("sequential_soaks_are_continuous") is not False
                or continuity.get("stitched_processes_count_toward_gate") is not False
                or continuity.get("counts_toward_gate") is not False
                or continuity.get("stitch_claim") is not False
                or continuity.get("rule") != "one_live_soak_process"
            ):
                _add(violations, "stitched_process_boundaries")
        founder = score_report.get("founder_start_conditions")
        if not isinstance(founder, dict):
            _add(violations, "founder_start_conditions")
        else:
            if (
                founder.get("approval_is_a_start") is not False
                or founder.get("approval_claimed_as_start") is not False
                or founder.get("conditions_satisfied") is not False
                or founder.get("start_registration_present") is not False
                or founder.get("local_only_counts_as_public_evidence") is not False
                or founder.get("unknown_root_cause_allowed") is not False
                or founder.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is not False
                or founder.get("a_72h_pass_is_production_readiness") is not False
                or founder.get("can_start_clock") is not False
                or founder.get("l2_2_status") != "NOT_STARTED"
                or founder.get("clock_state") != "NOT_STARTED"
                or founder.get("production_7x24") != "NOT_ACCEPTED"
                or founder.get("rule") != "five_founder_conditions_before_start"
            ):
                _add(violations, "founder_start_conditions")
        scored_watchdog = score_report.get("supervisor_watchdog_honesty")
        if not _supervisor_row_ok(scored_watchdog, claims_required=False):
            _add(violations, "supervisor_watchdog_honesty")
        scored_implementation = score_report.get("supervisor_watchdog_implementation")
        if not _implementation_row_ok(scored_implementation):
            _add(violations, "supervisor_watchdog_implementation")
        scored_cadence = score_report.get("supervision_cadence_writer")
        if not _cadence_row_ok(scored_cadence):
            _add(violations, "supervision_cadence_writer")
        scored_attribution = score_report.get("failure_attribution")
        if not _attribution_row_ok(scored_attribution):
            _add(violations, "failure_attribution")
        scored_pack = score_report.get("public_evidence_pack")
        if not _pack_row_ok(scored_pack):
            _add(violations, "public_evidence_pack")
        blockers = score_report.get("gates", {}).get("blockers") if isinstance(score_report.get("gates"), dict) else []
        if not isinstance(blockers, list) or "supervisor_watchdog_offline_probe_is_not_condition_2" not in blockers:
            _add(violations, "supervisor_watchdog_honesty")
        if not isinstance(blockers, list) or "supervisor_watchdog_dummy_scaffold_is_not_condition_2" not in blockers:
            _add(violations, "supervisor_watchdog_implementation")
        if not isinstance(blockers, list) or "supervision_cadence_offline_exercise_is_not_condition_2" not in blockers:
            _add(violations, "supervision_cadence_writer")
        if (
            not isinstance(blockers, list)
            or "failure_attribution_sample_classification_is_not_condition_4" not in blockers
        ):
            _add(violations, "failure_attribution")
        if (
            not isinstance(blockers, list)
            or "public_evidence_pack_sample_validation_is_not_condition_3" not in blockers
        ):
            _add(violations, "public_evidence_pack")
        for name in score_mod.validate_report(score_report):
            if name == "forged_pass":
                _add(violations, "forged_pass")
            elif name == "forged_accept":
                _add(violations, "forged_can_accept_l2_2")
            elif name == "forged_close":
                _add(violations, "forged_can_close_l2_2")
            elif name == "forged_clock_start":
                _add(violations, "forged_can_start_clock")
            elif name == "production_claim":
                _add(violations, "forged_production_accepted")
            elif name == "status":
                _add(violations, "l2_2_status")
            elif name in {
                "additive_historical_shorts",
                "non_additivity",
                "stitched_process_boundaries",
                "process_continuity",
                "founder_start_conditions",
                "founder_conditions_missing",
                "approval_is_not_a_start",
                "local_only_refused",
                "local_only_evidence_refused",
                "unknown_root_cause_refused",
                "supervisor_watchdog_required",
                "supervisor_watchdog_honesty",
                "supervisor_watchdog_implementation",
                "supervision_cadence_writer",
                "failure_attribution",
                "failure_attribution_mismatch",
                "public_evidence_pack",
                "public_evidence_pack_mismatch",
                "condition_4_unsatisfied",
                "condition_3_unsatisfied",
                "scaffold_sha256sums_not_soak_evidence",
                "condition_2_unsatisfied",
                "offline_probe_is_not_supervisor_watchdog",
                "offline_probe_is_not_a_start",
            }:
                _add(violations, name)
            else:
                _add(violations, "score:" + name)
        _walk_claims(score_report, violations)

    if preflight_mod is not None:
        classified = preflight_mod.classify_r2(r2_text)
        r2_unfilled = (
            classified.get("unfilled") is True
            and classified.get("start_decision") == "not_given"
            and classified.get("ok") is True
        )
        if not r2_unfilled:
            _add(violations, "r2_checklist_not_blank")
        if isinstance(preflight_report, dict):
            checks = preflight_report.get("checks") if isinstance(preflight_report.get("checks"), dict) else {}
            r2_row = checks.get("r2_checklist") if isinstance(checks.get("r2_checklist"), dict) else {}
            report_unfilled = r2_row.get("unfilled") is True and r2_row.get("start_decision") == "not_given"
            if r2_unfilled != report_unfilled:
                _add(violations, "r2_disagrees")
        classified_sd = preflight_mod.classify_start_decision(start_decision_text)
        start_decision_unfilled = (
            classified_sd.get("unfilled") is True
            and classified_sd.get("start_decision") == "not_given"
            and classified_sd.get("ok") is True
        )
        if classified_sd.get("detail") == "forged_claim":
            _add(violations, "start_decision_forged")
        if not start_decision_unfilled:
            _add(violations, "start_decision_not_blank")
        if isinstance(preflight_report, dict):
            checks = preflight_report.get("checks") if isinstance(preflight_report.get("checks"), dict) else {}
            sd_row = checks.get("start_decision") if isinstance(checks.get("start_decision"), dict) else {}
            report_sd_unfilled = (
                sd_row.get("unfilled") is True
                and sd_row.get("start_decision") == "not_given"
                and sd_row.get("ok") is True
            )
            if start_decision_unfilled != report_sd_unfilled:
                _add(violations, "start_decision_disagrees")

    ok = not violations
    return {
        "ok": ok,
        "violations": violations,
        "l2_2_status": "NOT_STARTED" if ok else "WITHHELD",
        "clock_state": "NOT_STARTED" if ok else "WITHHELD",
        "soak_launched": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "r2_unfilled": r2_unfilled,
        "start_decision_unfilled": start_decision_unfilled,
        "stall_dut": "synthetic_temp_summary" if ok else "withheld",
        "ubuntu_24h_used_as_dut": False,
        "ubuntu_24h_counts_as_72h": False,
        "historical_shorts_are_additive": False,
        "sum_of_shorts_counts_toward_gate": False,
        "sequential_soaks_are_continuous": False,
        "stitched_processes_count_toward_gate": False,
        "founder_approval_is_a_start": False,
        "founder_conditions_satisfied": False,
        "founder_start_registration_present": False,
        "local_only_counts_as_public_evidence": False,
        "unknown_root_cause_allowed": False,
        "soak_dut_watchdog_counts_as_supervisor_watchdog": False,
        "condition_2_satisfied": False,
        "offline_probe_satisfies_condition_2": False,
        "offline_probe_is_supervisor_watchdog": False,
        "offline_probe_is_a_start": False,
        "is_supervisor_watchdog_of_live_supervisor": False,
        "dummy_crash_within_10s_passed": _dummy_exercise_passed(preflight_report, score_report) if ok else False,
        "dummy_tests_satisfy_condition_2": False,
        "implementation_satisfies_condition_2": False,
        "demonstrates_10_minute_supervision_cadence": False,
        "writes_on_schedule_passed": _cadence_exercise_passed(preflight_report, score_report) if ok else False,
        "late_write_meets_cadence": False,
        "classifies_sample_attributions_passed": (
            _attribution_exercise_passed(preflight_report, score_report) if ok else False
        ),
        "unknown_root_cause_rejected": (
            _attribution_exercise_passed(preflight_report, score_report) if ok else False
        ),
        "condition_4_satisfied": False,
        "attributes_live_soak_failure": False,
        "dummy_tests_satisfy_condition_4": False,
        "implementation_satisfies_condition_4": False,
        "classifies_or_validates_sample_public_pack_passed": (
            _pack_exercise_passed(preflight_report, score_report) if ok else False
        ),
        "local_only_pack_rejected": _pack_exercise_passed(preflight_report, score_report) if ok else False,
        "condition_3_satisfied": False,
        "packs_live_soak_evidence": False,
        "dummy_tests_satisfy_condition_3": False,
        "implementation_satisfies_condition_3": False,
        "scaffold_sha256sums_is_soak_evidence": False,
        "record_11s_later_meets_requirement": False,
        "a_72h_pass_is_production_readiness": False,
        "ubuntu_24h_specimen": specimen_view if ok else _specimen_view(None),
        "stall_hook_is_l2_2_acceptance": False,
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
        "pytest_is_l2_2_acceptance": False,
    }


def run_l2_2_assessment(root: Path | None = None) -> dict[str, Any]:
    """Subprocess the preflight and the not-started fixture. Does not launch soak."""
    repo = root or ROOT
    commands = l2_2_commands(repo)
    preflight_exit, preflight_report = _run_json(commands[0])
    score_exit, score_report = _run_json(commands[1])
    checklist = repo / R2_RELATIVE
    r2_text = checklist.read_text(encoding="utf-8") if checklist.is_file() else ""
    decision = repo / START_DECISION_RELATIVE
    start_decision_text = decision.read_text(encoding="utf-8") if decision.is_file() else ""
    return assess_l2_2_offline(
        preflight_report,
        score_report,
        r2_text=r2_text,
        preflight_exit=preflight_exit,
        score_exit=score_exit,
        start_decision_text=start_decision_text,
    )


def l2_2_offline_step() -> dict:
    assessment = run_l2_2_assessment()
    detail = "not_started_scaffold" if assessment["ok"] else ",".join(assessment["violations"])
    return step(
        "l2_2_offline",
        assessment["ok"] is True,
        detail[:500],
        l2_2_status=assessment["l2_2_status"],
        clock_state=assessment["clock_state"],
        soak_launched=False,
        production_7x24="NOT_ACCEPTED",
        can_start_clock=False,
        can_accept_l2_2=False,
        can_close_l2_2=False,
        r2_unfilled=assessment["r2_unfilled"],
        start_decision_unfilled=assessment["start_decision_unfilled"],
        stall_dut=assessment["stall_dut"],
        ubuntu_24h_used_as_dut=False,
        ubuntu_24h_counts_as_72h=False,
        historical_shorts_are_additive=False,
        sum_of_shorts_counts_toward_gate=False,
        sequential_soaks_are_continuous=False,
        stitched_processes_count_toward_gate=False,
        founder_approval_is_a_start=False,
        founder_conditions_satisfied=False,
        founder_start_registration_present=False,
        local_only_counts_as_public_evidence=False,
        unknown_root_cause_allowed=False,
        soak_dut_watchdog_counts_as_supervisor_watchdog=False,
        condition_2_satisfied=False,
        offline_probe_satisfies_condition_2=False,
        offline_probe_is_supervisor_watchdog=False,
        offline_probe_is_a_start=False,
        is_supervisor_watchdog_of_live_supervisor=False,
        dummy_crash_within_10s_passed=assessment["dummy_crash_within_10s_passed"],
        dummy_tests_satisfy_condition_2=False,
        implementation_satisfies_condition_2=False,
        demonstrates_10_minute_supervision_cadence=False,
        writes_on_schedule_passed=assessment["writes_on_schedule_passed"],
        late_write_meets_cadence=False,
        classifies_sample_attributions_passed=assessment["classifies_sample_attributions_passed"],
        unknown_root_cause_rejected=assessment["unknown_root_cause_rejected"],
        condition_4_satisfied=False,
        attributes_live_soak_failure=False,
        dummy_tests_satisfy_condition_4=False,
        implementation_satisfies_condition_4=False,
        classifies_or_validates_sample_public_pack_passed=assessment[
            "classifies_or_validates_sample_public_pack_passed"
        ],
        local_only_pack_rejected=assessment["local_only_pack_rejected"],
        condition_3_satisfied=False,
        packs_live_soak_evidence=False,
        dummy_tests_satisfy_condition_3=False,
        implementation_satisfies_condition_3=False,
        scaffold_sha256sums_is_soak_evidence=False,
        record_11s_later_meets_requirement=False,
        a_72h_pass_is_production_readiness=False,
        ubuntu_24h_specimen=assessment["ubuntu_24h_specimen"],
        stall_hook_is_l2_2_acceptance=False,
        gate_result="NOT_A_GATE",
        exit_0_is_gate_pass=False,
        violations=assessment["violations"],
    )


def run_pytest_step() -> dict:
    """Unit suite. A green suite does not accept L2-2 and does not start the clock."""
    base = {
        "is_l2_2_acceptance": False,
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "production_7x24": "NOT_ACCEPTED",
        "soak_launched": False,
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
    }
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return step("pytest_suite", True, "skipped_already_inside_pytest_not_an_acceptance", **base)
    if os.environ.get("HEALTH_CHECK_SKIP_PYTEST") == "1":
        return step("pytest_suite", True, "skipped_by_env_not_an_acceptance", **base)
    cmd = pytest_command()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    # Child health checks must not start another suite.
    env["HEALTH_CHECK_SKIP_PYTEST"] = "1"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return step("pytest_suite", False, "pytest_not_run:" + type(exc).__name__, **base)
    lines = [line for line in (proc.stdout or proc.stderr or "").splitlines() if line.strip()]
    last = lines[-1] if lines else ""
    return step(
        "pytest_suite",
        proc.returncode == 0,
        ("unit_suite_not_l2_2_acceptance:" + last)[:500],
        **base,
    )


def summarize(results: list[dict], overall: bool) -> dict[str, Any]:
    """This process never grants a start, an accept, or a close."""
    l2 = next((row for row in results if row.get("step") == "l2_2_offline"), None)
    if l2 is None:
        status, clock, checked, r2_unfilled, start_unfilled, stall_dut = (
            "NOT_STARTED",
            "NOT_STARTED",
            False,
            None,
            None,
            "withheld",
        )
    else:
        status = l2.get("l2_2_status", "WITHHELD")
        clock = l2.get("clock_state", "WITHHELD")
        checked = l2.get("ok") is True
        r2_unfilled = l2.get("r2_unfilled")
        start_unfilled = l2.get("start_decision_unfilled")
        stall_dut = l2.get("stall_dut", "withheld")
    raw_specimen = l2.get("ubuntu_24h_specimen") if l2 is not None and l2.get("ok") is True else None
    specimen = _specimen_view(raw_specimen)
    dummy_passed = (
        l2 is not None
        and l2.get("ok") is True
        and l2.get("dummy_crash_within_10s_passed") is True
        and l2.get("condition_2_satisfied") is not True
        and l2.get("dummy_tests_satisfy_condition_2") is not True
    )
    return {
        "overall_ok": overall,
        "l2_2_status": status,
        "clock_state": clock,
        "l2_2_checked": checked,
        "soak_launched": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "r2_unfilled": r2_unfilled,
        "start_decision_unfilled": start_unfilled,
        "stall_dut": stall_dut,
        "ubuntu_24h_used_as_dut": False,
        "ubuntu_24h_counts_as_72h": False,
        "historical_shorts_are_additive": False,
        "sum_of_shorts_counts_toward_gate": False,
        "sequential_soaks_are_continuous": False,
        "stitched_processes_count_toward_gate": False,
        "founder_approval_is_a_start": False,
        "founder_conditions_satisfied": False,
        "founder_start_registration_present": False,
        "local_only_counts_as_public_evidence": False,
        "unknown_root_cause_allowed": False,
        "soak_dut_watchdog_counts_as_supervisor_watchdog": False,
        "condition_2_satisfied": False,
        "offline_probe_satisfies_condition_2": False,
        "offline_probe_is_supervisor_watchdog": False,
        "offline_probe_is_a_start": False,
        "is_supervisor_watchdog_of_live_supervisor": False,
        "dummy_crash_within_10s_passed": dummy_passed,
        "dummy_tests_satisfy_condition_2": False,
        "implementation_satisfies_condition_2": False,
        "demonstrates_10_minute_supervision_cadence": False,
        "writes_on_schedule_passed": (
            l2 is not None
            and l2.get("ok") is True
            and l2.get("writes_on_schedule_passed") is True
            and l2.get("demonstrates_10_minute_supervision_cadence") is not True
            and l2.get("condition_2_satisfied") is not True
        ),
        "late_write_meets_cadence": False,
        "classifies_sample_attributions_passed": (
            l2 is not None
            and l2.get("ok") is True
            and l2.get("classifies_sample_attributions_passed") is True
            and l2.get("condition_4_satisfied") is not True
            and l2.get("attributes_live_soak_failure") is not True
        ),
        "unknown_root_cause_rejected": (
            l2 is not None
            and l2.get("ok") is True
            and l2.get("unknown_root_cause_rejected") is True
            and l2.get("unknown_root_cause_allowed") is not True
            and l2.get("condition_4_satisfied") is not True
        ),
        "condition_4_satisfied": False,
        "attributes_live_soak_failure": False,
        "dummy_tests_satisfy_condition_4": False,
        "implementation_satisfies_condition_4": False,
        "classifies_or_validates_sample_public_pack_passed": (
            l2 is not None
            and l2.get("ok") is True
            and l2.get("classifies_or_validates_sample_public_pack_passed") is True
            and l2.get("condition_3_satisfied") is not True
            and l2.get("packs_live_soak_evidence") is not True
        ),
        "local_only_pack_rejected": (
            l2 is not None
            and l2.get("ok") is True
            and l2.get("local_only_pack_rejected") is True
            and l2.get("local_only_counts_as_public_evidence") is not True
            and l2.get("condition_3_satisfied") is not True
        ),
        "condition_3_satisfied": False,
        "packs_live_soak_evidence": False,
        "dummy_tests_satisfy_condition_3": False,
        "implementation_satisfies_condition_3": False,
        "scaffold_sha256sums_is_soak_evidence": False,
        "record_11s_later_meets_requirement": False,
        "a_72h_pass_is_production_readiness": False,
        "ubuntu_24h_specimen": specimen,
        "stall_hook_is_l2_2_acceptance": False,
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
        "pytest_is_l2_2_acceptance": False,
        "results": results,
    }


def _emit(results: list[dict], overall: bool) -> None:
    print(json.dumps(summarize(results, overall), indent=2, ensure_ascii=False))


def main() -> int:
    results: list[dict] = []

    try:
        from control_plane.emergency_stop import is_stopped, STOP_PATH

        if is_stopped():
            results.append(step("emergency_stop", False, f"armed at {STOP_PATH}"))
            _emit(results, False)
            return 3
        results.append(step("emergency_stop", True, "not armed"))
    except Exception as e:
        results.append(step("emergency_stop", False, str(e)))

    try:
        from control_plane.control_plane import ControlPlane
        from control_plane.store import FileStore

        results.append(step("import_control_plane", True))
    except Exception as e:
        results.append(step("import_control_plane", False, str(e)))

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "l1_runner.py"), "--job", "dry_protocol_check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env={**dict(os.environ), "PYTHONPATH": str(ROOT)},
    )
    results.append(
        step(
            "l1_dry_protocol",
            r.returncode == 0,
            (r.stdout or r.stderr or "")[-200:],
        )
    )

    env = {**dict(os.environ), "PYTHONPATH": str(ROOT)}
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "experiments" / "exp02_auto_loop" / "cp_driven_loop.py"),
            "--reset",
            "--max-steps",
            "0",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    # seed one task via soak helper logic inline
    try:
        from control_plane.control_plane import ControlPlane
        from control_plane.store import FileStore
        from experiments.exp02_auto_loop.cp_driven_loop import STATE, ensure_goal
        import json as _json
        import time

        store = FileStore(STATE)
        cp = ControlPlane(store)
        gid = ensure_goal(cp)
        key = f"health-{int(time.time())}"
        t = cp.propose_task(
            gid,
            title=f"checksum:{key}",
            description=_json.dumps({"kind": "checksum", "payload": {"n": 7}}),
            proposed_by="health_check",
            estimated_cost_usd=0.0,
            idempotency_key=key,
            kind="checksum",
            payload={"n": 7},
        )
        cp.approve_task(t.id)
        results.append(step("seed_one", True, t.id))
    except Exception as e:
        results.append(step("seed_one", False, str(e)))

    r2 = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "l1_runner.py"),
            "--job",
            "auto_loop_once",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    results.append(
        step(
            "l1_auto_loop_once",
            r2.returncode == 0,
            (r2.stdout or "")[-300:],
        )
    )

    results.append(l2_2_offline_step())
    results.append(run_pytest_step())

    overall = all(x["ok"] for x in results)
    _emit(results, overall)
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
