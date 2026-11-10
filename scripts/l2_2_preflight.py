#!/usr/bin/env python3
"""Offline readiness check for the L2-2 72h scaffold.

Reads the repo. Parses documented flags. Classifies a synthetic fresh summary
and a synthetic stale summary through scripts/stall_watchdog.py. Reads
docs/progress/soak_2h/metrics.json only as a historical SHORT specimen
(Ubuntu-24H, wall about 86400.001s). That read is not a stall watch, not a
started L2-2 capture, and not the 72h gate. Refuses sums of ended SHORT walls
(including 86400.001 plus another 86400, and 86400 times 3) as a 72h capture.
Refuses stitching sequential or restarted
soak invocations into one capture, including a back-to-back pair, three
sequential 86400 soaks covering 72h of calendar time, and a wall that resets.
Records the Issue #9 conditional founder approval and refuses a report that
treats that approval as a start, pretends the five start conditions are
satisfied, counts LOCAL_ONLY as public evidence, ends on an unknown root
cause, or treats the soak-DUT stall watchdog as a watchdog of the supervisor.
Does not launch soak_2h.py, does not point the stall hook at the committed
Ubuntu-24H soak files, does not start the 72h clock, does not post an L2-2
START line, and does not register scheduled tasks.

Exit 0: an honest NOT_STARTED report whose not-started scaffold checks held.
Exit 2: an honest NOT_STARTED report whose checks did not all hold, or a report
that would have over-claimed and was refused.

Exit 0 is not a gate PASS. can_start_clock, can_accept_l2_2, and can_close_l2_2
stay false. Running this tool is not a start decision. Filling
START_DECISION.md is not a start decision.

docs/progress/l2_2/SHA256SUMS.json is a byte binding written by
scripts/evidence_sha256sums.py. A match is not a start, an accept, or a close.
This report verifies those bytes except its own file: the committed report
cannot record a digest of itself. tests/test_l2_2_preflight.py checks that
self digest.

  python3 scripts/l2_2_preflight.py
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "aistudioos-grok.l2-2.preflight.v1"
ROOT = Path(__file__).resolve().parents[1]
STOP_RELATIVE = Path("docs") / "progress" / "EMERGENCY_STOP"
CHECKLIST_RELATIVE = Path("docs") / "progress" / "l2_2" / "R2_CHECKLIST.md"
DECISION_RELATIVE = Path("docs") / "progress" / "l2_2" / "START_DECISION.md"
SCHEMA_RELATIVE = Path("docs") / "progress" / "l2_2" / "SCHEMA.json"
SUMS_RELATIVE = Path("docs") / "progress" / "l2_2" / "SHA256SUMS.json"
SELF_REPORT = "docs/progress/l2_2/scaffold/preflight.json"
FIXTURE_RELATIVE = Path("tests") / "fixtures" / "l2_2" / "scaffold_clock_not_started.json"
UBUNTU_24H_METRICS = Path("docs") / "progress" / "soak_2h" / "metrics.json"
UBUNTU_24H_WALL_S = 86400.001
UBUNTU_24H_MAX_WALL_S = 86400
UBUNTU_24H_EXPERIMENT = "UBUNTU-24H"
UBUNTU_24H_SHA_SHORT = "aaf8d24"
WALL_REQUIRED_SECONDS = 259200
SPECIMEN_ROLE = "historical_short_specimen"
REFUSED_SUMS = (
    ("ubuntu_24h_alone", (UBUNTU_24H_WALL_S,)),
    ("ubuntu_24h_plus_another_86400", (UBUNTU_24H_WALL_S, 86400.0)),
    ("three_times_86400", (86400.0, 86400.0, 86400.0)),
    ("ubuntu_24h_plus_two_86400", (UBUNTU_24H_WALL_S, 86400.0, 86400.0)),
)
REFUSED_SUM_EXPECTED = {
    "ubuntu_24h_alone": (86400.001, False, 1),
    "ubuntu_24h_plus_another_86400": (172800.001, False, 2),
    "three_times_86400": (259200.0, True, 3),
    "ubuntu_24h_plus_two_86400": (259200.001, True, 3),
}
# In-memory ended soaks. No metrics file is created for these. The pair sits
# back-to-back. The trio covers 72h of calendar time. The reset series is one
# wall counter that goes backwards. None of them is one live process.
REFUSED_STITCHES = (
    ("pair_86400_back_to_back", "sequential", (86400.0, 86400.0), 8100),
    ("trio_86400_calendar_72h", "sequential", (86400.0, 86400.0, 86400.0), 8200),
    ("wall_reset_three_86400", "reset", (0.0, 86400.0, 0.0, 86400.0, 0.0, 86400.0), 0),
)
REFUSED_STITCH_EXPECTED = {
    "pair_86400_back_to_back": {
        "invocation_count": 2,
        "distinct_start_count": 2,
        "distinct_process_count": 2,
        "segment_count": 2,
        "same_host": True,
        "wall_reset": False,
        "back_to_back": True,
        "walls_seconds": [86400.0, 86400.0],
        "wall_samples": None,
        "stitched_duration_seconds": 172800.0,
        "calendar_span_seconds": 172800.0,
        "stitched_duration_reaches_259200": False,
        "calendar_span_reaches_259200": False,
    },
    "trio_86400_calendar_72h": {
        "invocation_count": 3,
        "distinct_start_count": 3,
        "distinct_process_count": 3,
        "segment_count": 3,
        "same_host": True,
        "wall_reset": False,
        "back_to_back": True,
        "walls_seconds": [86400.0, 86400.0, 86400.0],
        "wall_samples": None,
        "stitched_duration_seconds": 259200.0,
        "calendar_span_seconds": 259200.0,
        "stitched_duration_reaches_259200": True,
        "calendar_span_reaches_259200": True,
    },
    "wall_reset_three_86400": {
        "invocation_count": 0,
        "distinct_start_count": 0,
        "distinct_process_count": 0,
        "segment_count": 3,
        "same_host": False,
        "wall_reset": True,
        "back_to_back": False,
        "walls_seconds": [],
        "wall_samples": [0.0, 86400.0, 0.0, 86400.0, 0.0, 86400.0],
        "stitched_duration_seconds": 259200.0,
        "calendar_span_seconds": None,
        "stitched_duration_reaches_259200": True,
        "calendar_span_reaches_259200": False,
    },
}
SPECIMEN_SHORT_DETAIL = "historical_short_not_72h_gate"
SPECIMEN_WITHHELD_DETAILS = frozenset(
    {
        "missing",
        "unreadable",
        "malformed",
        "wall_missing",
        "max_wall_missing",
        "scorer_import",
        "wall_bar_drift",
        "refused_as_72h",
        "not_the_committed_specimen",
    }
)

# Source files the sums file must list. The self report is listed too, but its
# digest is checked by tests rather than by the report that would rewrite it.
BOUND_SOURCES = (
    "docs/progress/l2_2/README.md",
    "docs/progress/l2_2/R2_CHECKLIST.md",
    "docs/progress/l2_2/SCHEMA.json",
    "docs/progress/l2_2/START_DECISION.md",
    "docs/progress/l2_2/scaffold/preflight.json",
    "docs/progress/l2_2/scaffold/report.json",
)

# The README start line. Parsed only. Never executed.
DOCUMENTED_ARGV = [
    "--cycles",
    "5000",
    "--interval",
    "60",
    "--via-l1",
    "--seed",
    "300",
    "--idle-policy",
    "reseed",
    "--max-wall-seconds",
    "259200",
]

REQUIRED_PATHS = (
    "scripts/l2_2_score.py",
    "scripts/l2_2_preflight.py",
    "scripts/coverage_gap_log.py",
    "scripts/supervision_monitor.py",
    "scripts/stall_watchdog.py",
    "scripts/soak_2h.py",
    "docs/progress/l2_2/R2_CHECKLIST.md",
    "docs/progress/l2_2/START_DECISION.md",
    "docs/progress/l2_2/SCHEMA.json",
    "docs/progress/l2_2/README.md",
    "docs/progress/l2_2/scaffold/report.json",
    "docs/progress/l2_2/scaffold/preflight.json",
    "docs/progress/l2_2/SHA256SUMS.json",
    "tests/fixtures/l2_2/scaffold_clock_not_started.json",
    "tests/fixtures/l2_2/scaffold_exit0_only.json",
    "tests/fixtures/l2_2/scaffold_full_wall_cannot_accept.json",
    "tests/fixtures/l2_2/scaffold_interactive_forbidden.json",
    "tests/fixtures/l2_2/scaffold_naive_timestamp.json",
    "tests/fixtures/l2_2/scaffold_wall_short.json",
    "tests/test_l2_2_score.py",
    "tests/test_coverage_gap_log.py",
)

CHECK_ORDER = (
    "scaffold_files",
    "evidence_sums",
    "contract",
    "soak_flags",
    "r2_checklist",
    "start_decision",
    "emergency_stop",
    "gap_logger",
    "supervision_monitor",
    "stall_watchdog",
    "ubuntu_24h_specimen",
    "non_additivity",
    "process_continuity",
    "founder_start_conditions",
    "scorer_refuses",
)

GATE_KEYS = ("can_accept_l2_2", "can_close_l2_2", "can_start_clock")
UNFILLED_MARK = "The copy in git is unfilled."
START_TEMPLATE = "**Not given**"
OPERATOR_PREFIX = "Who decided"

OPERATOR_NOTE = (
    "Running this preflight is not a start decision. "
    "Filling R2_CHECKLIST.md is not a start decision. "
    "Filling START_DECISION.md is not a start decision. "
    "A matching SHA256SUMS.json is not a start decision. "
    "The stall-watchdog hook is not a start decision and is not L2-2 acceptance. "
    "The Ubuntu-24H metrics file is a historical SHORT specimen. Recording it does not start the 72h clock, does not count it as 72h, and does not make it the stall DUT. "
    "Historical SHORT walls are not additive toward 259200. A sum of ended 24h walls does not start the 72h clock and does not count toward the gate. "
    "Sequential or restarted soak invocations are not one continuous 72h wall. Stitching them, even back-to-back on the same host, does not start the 72h clock and does not count toward the gate. "
    "The Issue #9 conditional founder approval is not a start decision. The five start conditions are unfilled. LOCAL_ONLY is not public evidence. Unknown root cause is not a terminal attribution. The soak-DUT stall watchdog is not a watchdog of the supervisor. "
    "Exit 0 is an honest NOT_STARTED report, not a gate PASS, and it does not launch soak_2h.py."
)

# The documented command recorded in START_DECISION.md. Parsed nowhere. Never executed.
INTENDED_COMMAND = "soak_2h.py --via-l1 --idle-policy reseed --max-wall-seconds 259200"
_NOT_STARTED_RE = re.compile(r"not[\s_\-]*started", re.IGNORECASE)
_NOT_ACCEPTED_RE = re.compile(r"not[\s_\-]*accepted", re.IGNORECASE)
_NOT_GIVEN_RE = re.compile(r"not[\s_\-]*given", re.IGNORECASE)
_BAD_WORD_RE = re.compile(r"\b(?:started|accepted|pass|given|approved)\b", re.IGNORECASE)
_GATE_TRUE_RE = re.compile(
    r"""can_(?:start_clock|accept_l2_2|close_l2_2)[`"' \t\r\n:=*]{0,40}true\b""",
    re.IGNORECASE,
)

NEXT_STEPS = (
    "This preflight did not start the 72h clock and did not launch soak_2h.py.",
    "Exit 0 is an honest NOT_STARTED report, not a gate PASS and not permission to start.",
    "Leave R2_CHECKLIST.md unfilled until a separate explicit start decision. Filling the checklist is not that decision.",
    "Leave START_DECISION.md unfilled with decision Not given. Filling that file does not start the soak.",
    "Do not register, create, or enable Interactive console scheduled tasks.",
    "Leave the 2026-11-03..06 L2-4 reconstruction INCOMPLETE on PR #11. Do not re-capture that window.",
    "SHA256SUMS.json binds scaffold bytes only. It is not permission to start.",
    "The stall-watchdog hook classified synthetic summaries only. It did not watch the Ubuntu-24H soak files and it did not start the 72h clock.",
    "The committed Ubuntu-24H metrics file is a historical SHORT specimen (wall 86400.001s, below 259200). It does not count toward the 72h gate and it is not the stall DUT. This preflight does not wrap it as a started capture.",
    "Historical SHORT walls are not additive. Ubuntu-24H 86400.001s plus another 86400s, or 86400s times 3, is not one continuous monotonic wall and is not a started L2-2 capture. This gate is not a start.",
    "Sequential or restarted soak invocations are not one live process. A back-to-back 86400s pair, three sequential 86400s soaks covering 72h of calendar time, or a wall that resets, is not a started L2-2 capture. This continuity gate is not a start.",
    "Issue #9 comment 6761044915 is a conditional founder approval, not a start and not a PASS. The five conditions stay unfilled in the committed templates. This preflight does not post an L2-2 START line and does not set can_start_clock.",
    "Production 7x24 stays NOT ACCEPTED. A 72h result is not production readiness. The observation track accepts or rejects. This preflight does not.",
)


def default_stop_path(root: Path | None = None) -> Path:
    return (root or ROOT) / STOP_RELATIVE


def _display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "outside_root"


def _table_cells(text: str, label: str) -> list[str] | None:
    want = label.lower()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and cells[0].lower() == want:
            return cells
    return None


def _table_cell(text: str, label: str) -> str | None:
    cells = _table_cells(text, label)
    if cells is None:
        return None
    return cells[1] if len(cells) > 1 else ""


def _start_row(text: str) -> tuple[str, str] | None:
    cells = _table_cells(text, "start decision")
    if cells is None:
        return None
    template = cells[1] if len(cells) > 1 else ""
    operator = cells[2] if len(cells) > 2 else ""
    return template, operator


def classify_r2(text: str) -> dict[str, Any]:
    """Blank-template check. A changed cell is still not a clock start."""
    row = _start_row(text)
    if row is None:
        return {
            "ok": False,
            "present": True,
            "unfilled": False,
            "start_decision": "row_missing",
            "detail": "start_decision_row_missing",
        }
    template, operator = row
    template_blank = template == START_TEMPLATE
    operator_blank = operator.startswith(OPERATOR_PREFIX)
    markers = (
        UNFILLED_MARK in text
        and "NOT STARTED" in text
        and "can_start_clock" in text
        and "259200" in text
    )
    if template_blank and operator_blank and markers:
        return {
            "ok": True,
            "present": True,
            "unfilled": True,
            "start_decision": "not_given",
            "detail": "blank_template",
        }
    decision = "not_given" if template_blank else "blank_template_changed"
    return {
        "ok": False,
        "present": True,
        "unfilled": False,
        "start_decision": decision,
        "detail": "checklist_not_blank",
    }


def _start_decision_forged(text: str) -> bool:
    """True when the template claims a start, PASS, ACCEPTED, or an open gate.

    Honest negations (NOT STARTED, NOT ACCEPTED, Not given) are not claims.
    The matched wording is not copied into the report.
    """
    for line in text.splitlines():
        low = line.lower()
        if re.search(r"\btrue\b", low) and any(
            key in low for key in ("can_start_clock", "can_accept_l2_2", "can_close_l2_2")
        ):
            return True
    if _GATE_TRUE_RE.search(text):
        return True
    scrubbed = _NOT_STARTED_RE.sub(" ", text)
    scrubbed = _NOT_ACCEPTED_RE.sub(" ", scrubbed)
    scrubbed = _NOT_GIVEN_RE.sub(" ", scrubbed)
    return _BAD_WORD_RE.search(scrubbed) is not None


def _start_decision_blank(text: str) -> bool:
    decision = _table_cell(text, "Decision status")
    who = _table_cell(text, "Who")
    utc = _table_cell(text, "UTC time")
    host = _table_cell(text, "Host")
    command = _table_cell(text, "Intended command")
    if decision != START_TEMPLATE:
        return False
    if who != "unfilled" or utc != "unfilled" or host != "unfilled":
        return False
    if command is None or INTENDED_COMMAND not in command:
        return False
    required = (
        UNFILLED_MARK,
        "NOT STARTED",
        "NOT ACCEPTED",
        "can_start_clock",
        "stay false",
        "Filling this file alone does not start the soak",
        "259200",
        "out of scope",
        "founder",
        "Interactive",
    )
    return all(mark in text for mark in required)


def classify_start_decision(text: str) -> dict[str, Any]:
    """Blank start-decision check. A forged claim is still not a clock start."""
    forged = _start_decision_forged(text)
    decision_cell = _table_cell(text, "Decision status")
    base = {
        "present": True,
        "binds_clock_start": False,
    }
    if forged:
        return {
            **base,
            "ok": False,
            "unfilled": False,
            "start_decision": "forge_refused",
            "detail": "forged_claim",
        }
    if _start_decision_blank(text):
        return {
            **base,
            "ok": True,
            "unfilled": True,
            "start_decision": "not_given",
            "detail": "blank_template",
        }
    decision = "not_given" if decision_cell == START_TEMPLATE else "blank_template_changed"
    return {
        **base,
        "ok": False,
        "unfilled": False,
        "start_decision": decision,
        "detail": "not_blank",
    }


def _check_files(root: Path) -> dict[str, Any]:
    missing = [rel for rel in REQUIRED_PATHS if not (root / rel).is_file()]
    return {
        "ok": not missing,
        "missing": missing,
        "detail": "present" if not missing else "missing:" + ",".join(missing),
    }


def _sums_result(
    ok: bool,
    *,
    present: bool,
    count: int,
    mismatched: list[str],
    missing_from_sums: list[str],
    self_report_listed: bool,
    detail: str,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "present": present,
        "count": count,
        "mismatched": mismatched,
        "missing_from_sums": missing_from_sums,
        "self_report": SELF_REPORT,
        "self_report_listed": self_report_listed,
        "self_digest_checked_by": "tests/test_l2_2_preflight.py",
        "binds_clock_start": False,
        "detail": detail,
    }


def _repo_file(root: Path, rel: str) -> Path | None:
    rel = rel.replace("\\", "/")
    parts = Path(rel).parts
    if not rel or rel.startswith("/") or ".." in parts:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _sums_overclaims(node: Any) -> bool:
    """True when a sums document tries to smuggle a start, accept, close, or PASS."""
    if isinstance(node, dict):
        if node.get("l2_2_status") == "PASS":
            return True
        if node.get("clock_state") == "STARTED":
            return True
        if node.get("production_7x24") == "ACCEPTED":
            return True
        for key in GATE_KEYS:
            if node.get(key) is True:
                return True
        return any(_sums_overclaims(value) for value in node.values())
    if isinstance(node, list):
        return any(_sums_overclaims(value) for value in node)
    return False


def _check_sums(root: Path, path: Path) -> dict[str, Any]:
    """Verify SHA256SUMS.json against the tree. Does not start the clock.

    The digest function is evidence_sha256sums.sha256_file. This check does not
    compare SELF_REPORT: writing that result into the report would change the
    bytes the sums file binds. The test module recomputes that digest.
    """
    blank = list(BOUND_SOURCES)
    if not path.is_file():
        return _sums_result(
            False,
            present=False,
            count=0,
            mismatched=[],
            missing_from_sums=blank,
            self_report_listed=False,
            detail="missing",
        )
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _sums_result(
            False,
            present=True,
            count=0,
            mismatched=[],
            missing_from_sums=blank,
            self_report_listed=False,
            detail="unreadable",
        )
    if not isinstance(doc, dict):
        return _sums_result(
            False,
            present=True,
            count=0,
            mismatched=[],
            missing_from_sums=blank,
            self_report_listed=False,
            detail="malformed",
        )
    try:
        from evidence_sha256sums import sha256_file
    except Exception:
        return _sums_result(
            False,
            present=True,
            count=0,
            mismatched=[],
            missing_from_sums=blank,
            self_report_listed=False,
            detail="hasher_import",
        )
    files = doc.get("files")
    overclaim = _sums_overclaims(doc)
    listed: dict[str, tuple[str, int]] = {}
    malformed = not isinstance(files, list) or not isinstance(doc.get("count"), int)
    if isinstance(files, list):
        malformed = malformed or doc.get("count") != len(files)
        for entry in files:
            if not isinstance(entry, dict):
                malformed = True
                continue
            rel = entry.get("path")
            digest = entry.get("sha256")
            size = entry.get("bytes")
            if (
                not isinstance(rel, str)
                or not isinstance(digest, str)
                or isinstance(size, bool)
                or not isinstance(size, int)
            ):
                malformed = True
                continue
            rel = rel.replace("\\", "/")
            if rel in listed:
                malformed = True
            listed[rel] = (digest, size)
    git_head = doc.get("git_head")
    utc = doc.get("utc")
    git_head_ok = isinstance(git_head, str) and len(git_head) == 40 and all(
        char in "0123456789abcdef" for char in git_head
    )
    utc_ok = isinstance(utc, str) and bool(utc)
    if not git_head_ok or not utc_ok:
        malformed = True
    mismatched: list[str] = []
    missing_on_disk: list[str] = []
    for rel in sorted(listed):
        if rel == SELF_REPORT:
            continue
        file_path = _repo_file(root, rel)
        digest, size = listed[rel]
        if file_path is None or not file_path.is_file():
            missing_on_disk.append(rel)
            continue
        if file_path.stat().st_size != size or sha256_file(file_path) != digest:
            mismatched.append(rel)
    required_missing = [rel for rel in BOUND_SOURCES if rel not in listed]
    self_listed = SELF_REPORT in listed
    if overclaim:
        detail = "overclaim"
    elif malformed:
        detail = "malformed"
    elif mismatched or missing_on_disk:
        detail = "mismatch"
    elif required_missing or not self_listed:
        detail = "incomplete_manifest"
    else:
        detail = "bound_not_a_start"
    return _sums_result(
        detail == "bound_not_a_start",
        present=True,
        count=len(listed),
        mismatched=mismatched + missing_on_disk,
        missing_from_sums=required_missing,
        self_report_listed=self_listed,
        detail=detail,
    )


def _check_contract(root: Path) -> dict[str, Any]:
    path = root / SCHEMA_RELATIVE
    if not path.is_file():
        return {"ok": False, "detail": "schema_missing"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "detail": "schema_unreadable"}
    emitted = doc.get("l2_2_status_emitted")
    ok = (
        doc.get("preflight_schema") == SCHEMA
        and doc.get("wall_required_seconds") == 259200
        and doc.get("production_7x24") == "NOT_ACCEPTED"
        and doc.get("can_accept_l2_2") is False
        and doc.get("can_close_l2_2") is False
        and doc.get("can_start_clock") is False
        and isinstance(emitted, list)
        and "PASS" not in emitted
    )
    founder = doc.get("founder_start_conditions") if isinstance(doc.get("founder_start_conditions"), dict) else {}
    try:
        import l2_2_score as l2_contract
    except Exception:
        l2_contract = None
    founder_ok = (
        l2_contract is not None
        and founder.get("approval_is_a_start") is False
        and founder.get("conditions_satisfied") is False
        and founder.get("can_start_clock") is False
        and founder.get("start_registration_present") is False
        and founder.get("local_only_counts_as_public_evidence") is False
        and founder.get("unknown_root_cause_allowed") is False
        and founder.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is False
        and founder.get("a_72h_pass_is_production_readiness") is False
        and founder.get("approval_comment_id") == l2_contract.FOUNDER_APPROVAL_COMMENT_ID
        and founder.get("approval_utc") == l2_contract.FOUNDER_APPROVAL_UTC
        and founder.get("approval_issue") == l2_contract.FOUNDER_APPROVAL_ISSUE
        and founder.get("approval_target_pr") == l2_contract.FOUNDER_APPROVAL_PR
        and founder.get("condition_ids") == list(l2_contract.FOUNDER_CONDITION_IDS)
        and founder.get("supervision_write_max_seconds") == l2_contract.SUPERVISION_WRITE_MAX_SECONDS
        and founder.get("supervisor_watchdog_max_seconds") == l2_contract.SUPERVISOR_WATCHDOG_MAX_SECONDS
    )
    ok = ok and founder_ok
    return {
        "ok": ok,
        "preflight_schema": doc.get("preflight_schema") if doc.get("preflight_schema") == SCHEMA else "mismatch",
        "wall_required_seconds": doc.get("wall_required_seconds"),
        "detail": "contract_refuses_gates" if ok else "contract_drift",
    }


def _check_soak_flags() -> dict[str, Any]:
    try:
        import soak_2h
    except Exception as exc:
        return {"ok": False, "executed": False, "detail": f"import:{type(exc).__name__}"}
    try:
        args = soak_2h.build_parser().parse_args(list(DOCUMENTED_ARGV))
    except SystemExit:
        return {"ok": False, "executed": False, "detail": "argparse_rejected"}
    except Exception as exc:
        return {"ok": False, "executed": False, "detail": f"parser_error:{type(exc).__name__}"}
    ok = (
        args.via_l1 is True
        and args.idle_policy == "reseed"
        and args.max_wall_seconds == 259200
        and args.cycles == 5000
        and args.interval == 60
        and args.seed == 300
    )
    return {
        "ok": ok,
        "action": "argparse_only",
        "executed": False,
        "via_l1": args.via_l1 is True,
        "idle_policy": args.idle_policy,
        "max_wall_seconds": args.max_wall_seconds,
        "cycles": args.cycles,
        "interval": args.interval,
        "seed": args.seed,
        "detail": "parsed_not_executed" if ok else "documented_flags_mismatch",
    }


def _check_r2(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "ok": False,
            "present": False,
            "unfilled": False,
            "start_decision": "absent",
            "detail": "missing",
        }
    return classify_r2(path.read_text(encoding="utf-8"))


def _check_start_decision(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "ok": False,
            "present": False,
            "unfilled": False,
            "start_decision": "absent",
            "binds_clock_start": False,
            "detail": "missing",
        }
    return classify_start_decision(path.read_text(encoding="utf-8"))


def _check_stop(path: Path, root: Path) -> dict[str, Any]:
    present = path.is_file()
    return {
        "ok": not present,
        "flag_present": present,
        "path": _display(path, root),
        "detail": "absent" if not present else "present_left_untouched",
    }


def _check_gap_logger() -> dict[str, Any]:
    try:
        import coverage_gap_log as gaplog

        record = gaplog.build_record(
            gap_seconds=30,
            source="operator_sample",
            timestamp="2026-02-01T00:00:30Z",
        )
    except Exception as exc:
        return {"ok": False, "detail": f"gap_logger:{type(exc).__name__}"}
    ok = (
        gaplog.YELLOW_MIN_SECONDS == 13.0
        and gaplog.RED_MIN_SECONDS == 300.0
        and record.get("band") == "yellow"
        and record.get("implies_soak_complete") is False
        and record.get("clock_effect") == "none"
        and record.get("coverage_gap") is True
    )
    return {
        "ok": ok,
        "schema": gaplog.SCHEMA,
        "sample_band": record.get("band"),
        "sample_timestamp": record.get("timestamp"),
        "implies_soak_complete": False,
        "clock_effect": "none",
        "appended": False,
        "detail": "sample_not_appended" if ok else "gap_logger_contract",
    }


def _check_monitor() -> dict[str, Any]:
    try:
        import coverage_gap_log as gaplog
        import supervision_monitor
    except Exception as exc:
        return {"ok": False, "executed": False, "detail": f"import:{type(exc).__name__}"}
    try:
        args = supervision_monitor.build_parser().parse_args(["--live-dut"])
    except SystemExit:
        return {"ok": False, "executed": False, "detail": "argparse_rejected"}
    except Exception as exc:
        return {"ok": False, "executed": False, "detail": f"parser_error:{type(exc).__name__}"}
    wired = supervision_monitor.gaplog is gaplog
    live = args.live_dut is True
    has_observe = callable(getattr(supervision_monitor, "observe", None))
    ok = wired and live and has_observe
    return {
        "ok": ok,
        "action": "argparse_only",
        "wired_to_gap_logger": wired,
        "live_dut_switch_parses": live is True,
        "executed": False,
        "detail": "parsed_not_executed" if ok else "unwired",
    }


def _closed_stall(detail: str, **extra: Any) -> dict[str, Any]:
    """Honest stall-hook row. Claim fields stay closed even when the probe failed."""
    row: dict[str, Any] = {
        "ok": False,
        "action": "synthetic_mtime",
        "tool": "scripts/stall_watchdog.py",
        "dut": "synthetic_temp_summary",
        "ubuntu_24h_used_as_dut": False,
        "default_summary_used": False,
        "fresh_stalled": False,
        "stale_stalled": False,
        "fresh_exit": None,
        "stale_exit": None,
        "fresh_gap_band": None,
        "stale_gap_band": None,
        "gap_source": "operator_sample",
        "gap_appended": False,
        "gap_implies_soak_complete": False,
        "composed_with": "scripts/coverage_gap_log.py",
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "soak_launched": False,
        "binds_clock_start": False,
        "implies_l2_2_acceptance": False,
        "implies_72h_pass": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "repo_alert_written": False,
        "alert_left_in_repo": False,
        "max_idle_minutes": 15.0,
        "stall_idle_seconds": 900.0,
        "gap_red_exclusive_min_seconds": 300.0,
        "detail": detail,
    }
    row.update(extra)
    row["l2_2_status"] = "NOT_STARTED"
    row["clock_state"] = "NOT_STARTED"
    row["clock_effect"] = "none"
    row["soak_launched"] = False
    row["binds_clock_start"] = False
    row["implies_l2_2_acceptance"] = False
    row["implies_72h_pass"] = False
    row["production_7x24"] = "NOT_ACCEPTED"
    row["can_start_clock"] = False
    row["can_accept_l2_2"] = False
    row["can_close_l2_2"] = False
    row["ubuntu_24h_used_as_dut"] = False
    row["default_summary_used"] = False
    row["repo_alert_written"] = False
    row["alert_left_in_repo"] = False
    row["gap_appended"] = False
    row["gap_implies_soak_complete"] = False
    return row


def _probe_overclaims(result: dict[str, Any]) -> bool:
    """True when a probe result tries to start, accept, or use the ended soak as the DUT."""
    if result.get("binds_clock_start") is True or result.get("implies_l2_2_acceptance") is True:
        return True
    if result.get("implies_72h_pass") is True or result.get("soak_launched") is True:
        return True
    if result.get("clock_effect") not in {None, "none"}:
        return True
    if result.get("clock_state") not in {None, "NOT_STARTED"}:
        return True
    if result.get("l2_2_status") not in {None, "NOT_STARTED"}:
        return True
    if result.get("production_7x24") not in {None, "NOT_ACCEPTED"}:
        return True
    if result.get("ubuntu_24h_used_as_dut") is True or result.get("default_summary_used") is True:
        return True
    if result.get("repo_alert_written") is True or result.get("alert_left_in_repo") is True:
        return True
    if result.get("gap_implies_soak_complete") is True or result.get("gap_appended") is True:
        return True
    return any(result.get(key) is True for key in GATE_KEYS)


def _check_stall_watchdog() -> dict[str, Any]:
    """Classify synthetic fresh vs stale summaries. Does not launch soak or watch Ubuntu-24H."""
    try:
        import stall_watchdog as watchdog
    except Exception as exc:
        return _closed_stall(f"import:{type(exc).__name__}")
    if not callable(getattr(watchdog, "offline_probe", None)):
        return _closed_stall("probe_missing")
    try:
        result = watchdog.offline_probe()
    except Exception as exc:
        return _closed_stall(f"probe:{type(exc).__name__}")
    if not isinstance(result, dict):
        return _closed_stall("probe_malformed")
    overclaim = _probe_overclaims(result)
    fresh_stalled = result.get("fresh_stalled")
    stale_stalled = result.get("stale_stalled")
    fresh_band = result.get("fresh_gap_band")
    stale_band = result.get("stale_gap_band")
    fresh_exit = result.get("fresh_exit")
    stale_exit = result.get("stale_exit")
    classified = (
        result.get("ok") is True
        and result.get("action") == "synthetic_mtime"
        and result.get("dut") == "synthetic_temp_summary"
        and result.get("ubuntu_24h_used_as_dut") is False
        and result.get("default_summary_used") is False
        and fresh_stalled is False
        and stale_stalled is True
        and fresh_exit == 0
        and stale_exit == 1
        and fresh_band == "ok"
        and stale_band == "red"
        and result.get("gap_source") == "operator_sample"
        and result.get("gap_appended") is False
        and result.get("gap_implies_soak_complete") is False
        and result.get("composed_with") == "scripts/coverage_gap_log.py"
        and result.get("clock_effect") == "none"
        and result.get("soak_launched") is False
        and result.get("repo_alert_written") is False
        and result.get("alert_left_in_repo") is False
        and result.get("max_idle_minutes") == 15
        and result.get("stall_idle_seconds") == 900
        and not overclaim
    )
    if overclaim:
        detail = "probe_overclaim"
    elif classified:
        detail = "synthetic_fresh_vs_stale"
    else:
        raw = result.get("detail")
        allowed = {
            "classification_failed",
            "probe_missing",
            "probe_malformed",
            "synthetic_path_in_soak_tree",
            "default_summary",
        }
        prefixes = ("gap_logger:", "probe_io:", "gap_band:", "import:", "probe:")
        if isinstance(raw, str) and (raw in allowed or raw.startswith(prefixes)):
            detail = raw
        else:
            detail = "classification_failed"
    band_ok = fresh_band if fresh_band in {"ok", "yellow", "red"} else None
    band_stale = stale_band if stale_band in {"ok", "yellow", "red"} else None
    return _closed_stall(
        detail,
        ok=classified,
        fresh_stalled=fresh_stalled if isinstance(fresh_stalled, bool) else False,
        stale_stalled=stale_stalled if isinstance(stale_stalled, bool) else False,
        fresh_exit=fresh_exit if isinstance(fresh_exit, int) and not isinstance(fresh_exit, bool) else None,
        stale_exit=stale_exit if isinstance(stale_exit, int) and not isinstance(stale_exit, bool) else None,
        fresh_gap_band=band_ok,
        stale_gap_band=band_stale,
        max_idle_minutes=15.0,
        stall_idle_seconds=900.0,
        gap_red_exclusive_min_seconds=300.0,
    )


def _closed_specimen(detail: str, **extra: Any) -> dict[str, Any]:
    """Historical-specimen row. The L2-2 clock stays NOT_STARTED.

    A SHORT classification lives only in this nested row. It is not clock_state.
    Honesty flags are forced closed so a caller cannot publish the file as 72h,
    as acceptance, or as the stall DUT.
    """
    row: dict[str, Any] = {
        "ok": False,
        "role": SPECIMEN_ROLE,
        "path": UBUNTU_24H_METRICS.as_posix(),
        "experiment": None,
        "sha_short": None,
        "wall_elapsed_s": None,
        "max_wall_seconds": None,
        "wall_required_seconds": WALL_REQUIRED_SECONDS,
        "below_259200": False,
        "classification": "withheld",
        "ubuntu_24h_counts_as_72h": False,
        "counts_toward_72h_gate": False,
        "ubuntu_24h_used_as_dut": False,
        "is_stall_dut": False,
        "is_l2_2_acceptance": False,
        "binds_clock_start": False,
        "wrapped_as_started_capture": False,
        "clock_effect": "none",
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "soak_launched": False,
        "detail": detail,
    }
    for key in (
        "ok",
        "experiment",
        "sha_short",
        "wall_elapsed_s",
        "max_wall_seconds",
        "below_259200",
        "classification",
    ):
        if key in extra:
            row[key] = extra[key]
    row["role"] = SPECIMEN_ROLE
    row["path"] = UBUNTU_24H_METRICS.as_posix()
    row["wall_required_seconds"] = WALL_REQUIRED_SECONDS
    row["ubuntu_24h_counts_as_72h"] = False
    row["counts_toward_72h_gate"] = False
    row["ubuntu_24h_used_as_dut"] = False
    row["is_stall_dut"] = False
    row["is_l2_2_acceptance"] = False
    row["binds_clock_start"] = False
    row["wrapped_as_started_capture"] = False
    row["clock_effect"] = "none"
    row["l2_2_status"] = "NOT_STARTED"
    row["clock_state"] = "NOT_STARTED"
    row["production_7x24"] = "NOT_ACCEPTED"
    row["can_start_clock"] = False
    row["can_accept_l2_2"] = False
    row["can_close_l2_2"] = False
    row["soak_launched"] = False
    row["detail"] = detail
    wall = row.get("wall_elapsed_s")
    short = (
        row.get("ok") is True
        and row.get("classification") == "SHORT"
        and row.get("below_259200") is True
        and type(wall) is float
        and wall == UBUNTU_24H_WALL_S
        and wall < WALL_REQUIRED_SECONDS
        and row.get("max_wall_seconds") == UBUNTU_24H_MAX_WALL_S
        and row.get("experiment") == UBUNTU_24H_EXPERIMENT
        and row.get("sha_short") == UBUNTU_24H_SHA_SHORT
        and detail == SPECIMEN_SHORT_DETAIL
    )
    if not short:
        row["ok"] = False
        row["classification"] = "withheld"
        row["below_259200"] = False
        row["wall_elapsed_s"] = None
        row["max_wall_seconds"] = None
        row["experiment"] = None
        row["sha_short"] = None
        if detail == SPECIMEN_SHORT_DETAIL:
            row["detail"] = "not_the_committed_specimen"
    return row


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_ubuntu_specimen(path: Path) -> dict[str, Any]:
    """Read the committed Ubuntu-24H metrics file as a historical SHORT specimen.

    Does not call the scorer, does not build a capture with clock.started, and
    does not open the soak summary. The nested classification is SHORT. The
    L2-2 clock_state on this row stays NOT_STARTED.
    """
    if not path.is_file():
        return _closed_specimen("missing")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _closed_specimen("unreadable")
    if not isinstance(doc, dict):
        return _closed_specimen("malformed")
    wall = doc.get("wall_elapsed_s")
    max_wall = doc.get("max_wall_seconds")
    if not _is_number(wall):
        return _closed_specimen("wall_missing")
    if not _is_number(max_wall):
        return _closed_specimen("max_wall_missing")
    try:
        import l2_2_score as l2

        required = l2.WALL_REQUIRED_SECONDS
    except Exception:
        return _closed_specimen("scorer_import")
    if required != WALL_REQUIRED_SECONDS:
        return _closed_specimen("wall_bar_drift")
    if float(wall) >= float(required) or max_wall == required:
        return _closed_specimen("refused_as_72h")
    if (
        wall == UBUNTU_24H_WALL_S
        and max_wall == UBUNTU_24H_MAX_WALL_S
        and doc.get("experiment") == UBUNTU_24H_EXPERIMENT
        and doc.get("sha_short") == UBUNTU_24H_SHA_SHORT
    ):
        return _closed_specimen(
            SPECIMEN_SHORT_DETAIL,
            ok=True,
            experiment=UBUNTU_24H_EXPERIMENT,
            sha_short=UBUNTU_24H_SHA_SHORT,
            wall_elapsed_s=UBUNTU_24H_WALL_S,
            max_wall_seconds=UBUNTU_24H_MAX_WALL_S,
            below_259200=True,
            classification="SHORT",
        )
    return _closed_specimen("not_the_committed_specimen")


def _specimen_violations(specimen: Any) -> list[str]:
    """Reject a specimen row that relabels Ubuntu-24H as 72h, PASS, or the DUT."""
    violations: list[str] = []
    if not isinstance(specimen, dict):
        return ["ubuntu_24h_specimen"]
    if specimen.get("role") != SPECIMEN_ROLE or specimen.get("path") != UBUNTU_24H_METRICS.as_posix():
        violations.append("ubuntu_24h_specimen")
    if specimen.get("wall_required_seconds") != WALL_REQUIRED_SECONDS:
        violations.append("ubuntu_24h_as_72h")
    if specimen.get("ubuntu_24h_counts_as_72h") is not False or specimen.get("counts_toward_72h_gate") is not False:
        violations.append("ubuntu_24h_as_72h")
    if specimen.get("below_259200") is True and specimen.get("classification") != "SHORT":
        violations.append("ubuntu_24h_as_72h")
    wall = specimen.get("wall_elapsed_s")
    if wall is not None and (not _is_number(wall) or float(wall) >= WALL_REQUIRED_SECONDS):
        violations.append("ubuntu_24h_as_72h")
    if specimen.get("ubuntu_24h_used_as_dut") is not False or specimen.get("is_stall_dut") is not False:
        violations.append("ubuntu_24h_as_dut")
    if specimen.get("is_l2_2_acceptance") is not False:
        violations.append("ubuntu_24h_as_acceptance")
    if specimen.get("binds_clock_start") is not False or specimen.get("wrapped_as_started_capture") is not False:
        violations.append("ubuntu_24h_as_start")
    if specimen.get("soak_launched") is not False:
        violations.append("soak_launched")
    if specimen.get("clock_effect") != "none":
        violations.append("clock_effect")
    if specimen.get("l2_2_status") != "NOT_STARTED":
        violations.append("status")
    if specimen.get("clock_state") != "NOT_STARTED":
        violations.append("clock_state")
    if specimen.get("production_7x24") != "NOT_ACCEPTED":
        violations.append("production_claim")
    for key in GATE_KEYS:
        if specimen.get(key) is not False:
            violations.append("forged_" + key)
    classification = specimen.get("classification")
    detail = specimen.get("detail")
    if classification == "SHORT":
        short_ok = (
            specimen.get("ok") is True
            and specimen.get("below_259200") is True
            and type(wall) is float
            and wall == UBUNTU_24H_WALL_S
            and wall < WALL_REQUIRED_SECONDS
            and specimen.get("max_wall_seconds") == UBUNTU_24H_MAX_WALL_S
            and specimen.get("experiment") == UBUNTU_24H_EXPERIMENT
            and specimen.get("sha_short") == UBUNTU_24H_SHA_SHORT
            and detail == SPECIMEN_SHORT_DETAIL
        )
        if not short_ok:
            violations.append("ubuntu_24h_specimen")
    elif classification == "withheld":
        withheld_ok = (
            specimen.get("ok") is False
            and specimen.get("below_259200") is False
            and wall is None
            and specimen.get("max_wall_seconds") is None
            and specimen.get("experiment") is None
            and specimen.get("sha_short") is None
            and detail in SPECIMEN_WITHHELD_DETAILS
        )
        if not withheld_ok:
            violations.append("ubuntu_24h_specimen")
    elif classification == "PASS":
        violations.append("status")
    elif classification == "ACCEPTED":
        violations.append("ubuntu_24h_as_acceptance")
    elif classification in {"STARTED", "started"}:
        violations.append("ubuntu_24h_as_start")
    else:
        violations.append("ubuntu_24h_as_72h")
    return violations


def _closed_non_additivity(detail: str, **extra: Any) -> dict[str, Any]:
    """Non-additivity row. Sums of ended SHORT walls stay off the 72h gate.

    Honesty flags are forced closed. A naive sum that lands on 259200 is still
    not a continuous live soak, not a start, and not acceptance.
    """
    refused = extra.get("refused_sums")
    if not isinstance(refused, list):
        refused = []
    ok = extra.get("ok") is True
    row: dict[str, Any] = {
        "ok": ok,
        "rule": "one_continuous_monotonic_wall",
        "tool": "scripts/l2_2_score.py",
        "wall_required_seconds": WALL_REQUIRED_SECONDS,
        "historical_shorts_are_additive": False,
        "sum_of_shorts_counts_toward_gate": False,
        "known_committed_shorts": [
            {
                "id": "ubuntu_24h",
                "path": UBUNTU_24H_METRICS.as_posix(),
                "wall_elapsed_s": UBUNTU_24H_WALL_S,
                "counts_toward_gate": False,
                "committed_metrics_file": True,
            }
        ],
        "d1_windows_metrics_file": None,
        "d1_windows_bound_as_specimen": False,
        "refused_sums": refused,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "soak_launched": False,
        "binds_clock_start": False,
        "documented_soak_argv_executed": False,
        "detail": detail,
    }
    return row


def _scorer_refuses_additive_report(l2: Any, root: Path) -> bool:
    """True when the scorer rejects a report that relabels a 24h sum as 72h."""
    fixture = root / FIXTURE_RELATIVE
    if not fixture.is_file():
        return False
    try:
        honest = l2.score(l2.load_capture(fixture))
    except Exception:
        return False
    if not isinstance(honest, dict) or not isinstance(honest.get("non_additivity"), dict):
        return False
    forged = json.loads(json.dumps(honest))
    forged["non_additivity"]["historical_shorts_are_additive"] = True
    forged["non_additivity"]["sum_of_shorts_counts_toward_gate"] = True
    forged["non_additivity"]["counts_toward_gate"] = True
    forged["non_additivity"]["additive_claim"] = True
    forged["wall"]["components"] = [86400, 86400, 86400]
    forged["wall"]["counts_toward_gate"] = True
    forged["wall"]["elapsed_seconds"] = 259200
    forged["wall"]["source"] = "sum"
    forged["l2_2_status"] = "PASS"
    forged["clock_state"] = "WALL_OBSERVED"
    forged["production_7x24"] = "ACCEPTED"
    forged["gates"]["can_accept_l2_2"] = True
    forged["gates"]["can_start_clock"] = True
    names = set(l2.validate_report(forged))
    needed = {
        "additive_historical_shorts",
        "forged_pass",
        "production_claim",
        "forged_accept",
        "forged_clock_start",
    }
    return needed <= names


def _check_non_additivity(root: Path) -> dict[str, Any]:
    """Prove ended SHORT walls are not additive. Does not start the clock.

    The 86400 parts are in-memory ended walls. No Windows metrics file is
    created or bound. D1's documented wall is not a committed file in this tree.
    """
    try:
        import l2_2_score as l2
    except Exception:
        return _closed_non_additivity("scorer_import")
    if not callable(getattr(l2, "assess_short_sum", None)) or not callable(getattr(l2, "validate_report", None)):
        return _closed_non_additivity("assessor_missing")
    refused: list[dict[str, Any]] = []
    shape_ok = True
    for label, parts in REFUSED_SUMS:
        try:
            assessed = l2.assess_short_sum(list(parts))
        except Exception:
            return _closed_non_additivity("assessor_error")
        if not isinstance(assessed, dict):
            return _closed_non_additivity("assessor_malformed")
        total, naive, count = REFUSED_SUM_EXPECTED[label]
        lie = (
            assessed.get("counts_toward_gate") is not False
            or assessed.get("historical_shorts_are_additive") is not False
            or assessed.get("continuous_monotonic_wall") is not False
            or assessed.get("single_live_soak") is not False
            or assessed.get("sum_seconds") != total
            or assessed.get("naive_sum_reaches_259200") is not naive
            or assessed.get("component_count") != count
            or assessed.get("wall_required_seconds") != WALL_REQUIRED_SECONDS
        )
        if lie:
            shape_ok = False
        refused.append(
            {
                "label": label,
                "components_seconds": list(assessed.get("components_seconds") or []),
                "component_count": count,
                "sum_seconds": total,
                "wall_required_seconds": WALL_REQUIRED_SECONDS,
                "naive_sum_reaches_259200": naive,
                "counts_toward_gate": False,
                "historical_shorts_are_additive": False,
                "continuous_monotonic_wall": False,
                "single_live_soak": False,
            }
        )
    forged_refused = _scorer_refuses_additive_report(l2, root)
    ok = shape_ok and forged_refused
    if ok:
        detail = "shorts_not_additive"
    elif shape_ok:
        detail = "forged_sum_not_refused"
    else:
        detail = "sum_shape"
    return _closed_non_additivity(detail, ok=ok, refused_sums=refused)


def _non_additivity_violations(row: Any) -> list[str]:
    """Reject a preflight row that treats a sum of 24h walls as the 72h gate."""
    violations: list[str] = []
    if not isinstance(row, dict):
        return ["non_additivity"]
    if row.get("rule") != "one_continuous_monotonic_wall":
        violations.append("non_additivity")
    if row.get("tool") != "scripts/l2_2_score.py":
        violations.append("non_additivity")
    if row.get("historical_shorts_are_additive") is not False:
        violations.append("additive_historical_shorts")
    if row.get("sum_of_shorts_counts_toward_gate") is not False:
        violations.append("additive_historical_shorts")
    if row.get("d1_windows_bound_as_specimen") is not False or row.get("d1_windows_metrics_file") is not None:
        violations.append("non_additivity")
    if row.get("binds_clock_start") is not False or row.get("soak_launched") is not False:
        violations.append("additive_as_start")
    if row.get("documented_soak_argv_executed") is not False:
        violations.append("argv_executed")
    if row.get("clock_effect") != "none":
        violations.append("clock_effect")
    if row.get("l2_2_status") != "NOT_STARTED":
        violations.append("status")
    if row.get("clock_state") != "NOT_STARTED":
        violations.append("clock_state")
    if row.get("production_7x24") != "NOT_ACCEPTED":
        violations.append("production_claim")
    for key in GATE_KEYS:
        if row.get(key) is not False:
            violations.append("forged_" + key)
    shorts = row.get("known_committed_shorts")
    if not isinstance(shorts, list) or len(shorts) != 1 or not isinstance(shorts[0], dict):
        violations.append("non_additivity")
    else:
        only = shorts[0]
        if (
            only.get("id") != "ubuntu_24h"
            or only.get("path") != UBUNTU_24H_METRICS.as_posix()
            or only.get("wall_elapsed_s") != UBUNTU_24H_WALL_S
            or only.get("counts_toward_gate") is not False
            or only.get("committed_metrics_file") is not True
        ):
            violations.append("additive_historical_shorts")
    sums = row.get("refused_sums")
    if not isinstance(sums, list):
        violations.append("non_additivity")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in sums]
        if labels != [label for label, _parts in REFUSED_SUMS]:
            violations.append("non_additivity")
        else:
            for item in sums:
                label = item["label"]
                total, naive, count = REFUSED_SUM_EXPECTED[label]
                if (
                    item.get("sum_seconds") != total
                    or item.get("naive_sum_reaches_259200") is not naive
                    or item.get("component_count") != count
                    or item.get("wall_required_seconds") != WALL_REQUIRED_SECONDS
                    or item.get("counts_toward_gate") is not False
                    or item.get("historical_shorts_are_additive") is not False
                    or item.get("continuous_monotonic_wall") is not False
                    or item.get("single_live_soak") is not False
                ):
                    violations.append("additive_historical_shorts")
    if row.get("ok") is True and row.get("detail") != "shorts_not_additive":
        violations.append("non_additivity")
    if not isinstance(row.get("ok"), bool):
        violations.append("non_additivity")
    return violations


def _closed_process_continuity(detail: str, **extra: Any) -> dict[str, Any]:
    """Continuity row. Stitched soak processes stay off the 72h gate.

    Honesty flags are forced closed. A back-to-back pair, a 72h calendar of
    three 86400 soaks, or a wall that resets is still not one live process,
    not a start, and not acceptance.
    """
    refused = extra.get("refused_stitches")
    if not isinstance(refused, list):
        refused = []
    ok = extra.get("ok") is True
    return {
        "ok": ok,
        "rule": "one_live_soak_process",
        "tool": "scripts/l2_2_score.py",
        "wall_required_seconds": WALL_REQUIRED_SECONDS,
        "sequential_soaks_are_continuous": False,
        "stitched_processes_count_toward_gate": False,
        "counts_toward_gate": False,
        "d1_windows_metrics_file": None,
        "d1_windows_bound_as_specimen": False,
        "refused_stitches": refused,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "soak_launched": False,
        "binds_clock_start": False,
        "documented_soak_argv_executed": False,
        "detail": detail,
    }


def _scorer_refuses_stitched_report(l2: Any, root: Path) -> bool:
    """True when the scorer rejects a report that relabels a stitch as 72h."""
    fixture = root / FIXTURE_RELATIVE
    if not fixture.is_file():
        return False
    try:
        honest = l2.score(l2.load_capture(fixture))
    except Exception:
        return False
    if not isinstance(honest, dict) or not isinstance(honest.get("process_continuity"), dict):
        return False
    forged = json.loads(json.dumps(honest))
    forged["process_continuity"]["sequential_soaks_are_continuous"] = True
    forged["process_continuity"]["stitched_processes_count_toward_gate"] = True
    forged["process_continuity"]["counts_toward_gate"] = True
    forged["process_continuity"]["stitch_claim"] = True
    forged["wall"]["invocations"] = l2.synthetic_sequential_soaks([86400.0, 86400.0], pid_base=8100)
    forged["wall"]["counts_toward_gate"] = True
    forged["wall"]["stitch_claim"] = True
    forged["wall"]["elapsed_seconds"] = 172800
    forged["wall"]["source"] = "stitched"
    forged["l2_2_status"] = "PASS"
    forged["clock_state"] = "WALL_OBSERVED"
    forged["production_7x24"] = "ACCEPTED"
    forged["gates"]["can_accept_l2_2"] = True
    forged["gates"]["can_start_clock"] = True
    names = set(l2.validate_report(forged))
    needed = {
        "stitched_process_boundaries",
        "forged_pass",
        "production_claim",
        "forged_accept",
        "forged_clock_start",
    }
    return needed <= names


def _check_process_continuity(root: Path) -> dict[str, Any]:
    """Prove sequential soaks are not one continuous 72h. Does not start the clock.

    The soaks are in-memory. No metrics file is created or bound. Ubuntu-24H
    stays a historical SHORT specimen on its own row. D1 is not a file here.
    """
    try:
        import l2_2_score as l2
    except Exception:
        return _closed_process_continuity("scorer_import")
    if not callable(getattr(l2, "assess_process_continuity", None)) or not callable(
        getattr(l2, "validate_report", None)
    ):
        return _closed_process_continuity("assessor_missing")
    refused: list[dict[str, Any]] = []
    shape_ok = True
    compared = (
        "invocation_count",
        "distinct_start_count",
        "distinct_process_count",
        "segment_count",
        "same_host",
        "wall_reset",
        "back_to_back",
        "walls_seconds",
        "wall_samples",
        "stitched_duration_seconds",
        "calendar_span_seconds",
        "stitched_duration_reaches_259200",
        "calendar_span_reaches_259200",
    )
    for label, kind, parts, pid_base in REFUSED_STITCHES:
        try:
            if kind == "sequential":
                assessed = l2.assess_process_continuity(
                    l2.synthetic_sequential_soaks(list(parts), pid_base=pid_base)
                )
            else:
                assessed = l2.assess_process_continuity([], wall_samples=list(parts))
        except Exception:
            return _closed_process_continuity("assessor_error")
        if not isinstance(assessed, dict):
            return _closed_process_continuity("assessor_malformed")
        expected = REFUSED_STITCH_EXPECTED[label]
        lie = (
            assessed.get("counts_toward_gate") is not False
            or assessed.get("sequential_soaks_are_continuous") is not False
            or assessed.get("stitched_processes_count_toward_gate") is not False
            or assessed.get("single_live_process") is not False
            or assessed.get("wall_required_seconds") != WALL_REQUIRED_SECONDS
            or any(assessed.get(key) != expected[key] for key in compared)
        )
        if lie:
            shape_ok = False
        row = {
            "label": label,
            "wall_required_seconds": WALL_REQUIRED_SECONDS,
            "counts_toward_gate": False,
            "sequential_soaks_are_continuous": False,
            "stitched_processes_count_toward_gate": False,
            "single_live_process": False,
        }
        for key in compared:
            row[key] = expected[key]
        refused.append(row)
    forged_refused = _scorer_refuses_stitched_report(l2, root)
    ok = shape_ok and forged_refused
    if ok:
        detail = "stitches_not_continuous"
    elif shape_ok:
        detail = "forged_stitch_not_refused"
    else:
        detail = "stitch_shape"
    return _closed_process_continuity(detail, ok=ok, refused_stitches=refused)


def _process_continuity_violations(row: Any) -> list[str]:
    """Reject a preflight row that treats stitched soaks as the 72h gate."""
    violations: list[str] = []
    if not isinstance(row, dict):
        return ["process_continuity"]
    if row.get("rule") != "one_live_soak_process":
        violations.append("process_continuity")
    if row.get("tool") != "scripts/l2_2_score.py":
        violations.append("process_continuity")
    if row.get("sequential_soaks_are_continuous") is not False:
        violations.append("stitched_process_boundaries")
    if row.get("stitched_processes_count_toward_gate") is not False:
        violations.append("stitched_process_boundaries")
    if row.get("counts_toward_gate") is not False:
        violations.append("stitched_process_boundaries")
    if row.get("d1_windows_bound_as_specimen") is not False or row.get("d1_windows_metrics_file") is not None:
        violations.append("process_continuity")
    if row.get("binds_clock_start") is not False or row.get("soak_launched") is not False:
        violations.append("stitch_as_start")
    if row.get("documented_soak_argv_executed") is not False:
        violations.append("argv_executed")
    if row.get("clock_effect") != "none":
        violations.append("clock_effect")
    if row.get("l2_2_status") != "NOT_STARTED":
        violations.append("status")
    if row.get("clock_state") != "NOT_STARTED":
        violations.append("clock_state")
    if row.get("production_7x24") != "NOT_ACCEPTED":
        violations.append("production_claim")
    for key in GATE_KEYS:
        if row.get(key) is not False:
            violations.append("forged_" + key)
    stitches = row.get("refused_stitches")
    if not isinstance(stitches, list):
        violations.append("process_continuity")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in stitches]
        if labels != [label for label, _kind, _parts, _pid in REFUSED_STITCHES]:
            violations.append("process_continuity")
        else:
            compared = (
                "invocation_count",
                "distinct_start_count",
                "distinct_process_count",
                "segment_count",
                "same_host",
                "wall_reset",
                "back_to_back",
                "walls_seconds",
                "wall_samples",
                "stitched_duration_seconds",
                "calendar_span_seconds",
                "stitched_duration_reaches_259200",
                "calendar_span_reaches_259200",
            )
            for item in stitches:
                expected = REFUSED_STITCH_EXPECTED[item["label"]]
                if (
                    item.get("wall_required_seconds") != WALL_REQUIRED_SECONDS
                    or item.get("counts_toward_gate") is not False
                    or item.get("sequential_soaks_are_continuous") is not False
                    or item.get("stitched_processes_count_toward_gate") is not False
                    or item.get("single_live_process") is not False
                    or any(item.get(key) != expected[key] for key in compared)
                ):
                    violations.append("stitched_process_boundaries")
    if row.get("ok") is True and row.get("detail") != "stitches_not_continuous":
        violations.append("process_continuity")
    if not isinstance(row.get("ok"), bool):
        violations.append("process_continuity")
    return violations


FOUNDER_CLOSED_DETAILS = frozenset(
    {
        "approval_recorded_not_a_start",
        "templates_missing",
        "templates_not_blank",
        "start_registration_is_not_this_pass",
        "forged_founder_not_refused",
        "probe_failed",
        "scorer_import",
    }
)
FOUNDER_PROBE_LABELS = (
    "approval_is_not_a_start",
    "missing_condition",
    "local_only",
    "unknown_root_cause",
    "supervisor_without_watchdog",
    "soak_dut_watchdog_substituted",
)


def _founder_probe_row(label: str, assessed: dict[str, Any], condition_id: str) -> dict[str, Any]:
    detail = None
    for item in assessed.get("conditions") or []:
        if isinstance(item, dict) and item.get("id") == condition_id:
            detail = item.get("detail")
            break
    return {
        "label": label,
        "approval_is_a_start": False,
        "approval_is_a_pass": False,
        "approval_claimed_as_start": assessed.get("approval_claimed_as_start") is True,
        "start_registration_present": False,
        "start_registration_claimed": assessed.get("start_registration_claimed") is True,
        "conditions_satisfied": assessed.get("conditions_satisfied") is True,
        "missing_conditions": list(assessed.get("missing_conditions") or []),
        "local_only_refused": assessed.get("local_only_refused") is True,
        "local_only_counts_as_public_evidence": False,
        "unknown_root_cause_refused": assessed.get("unknown_root_cause_refused") is True,
        "unknown_root_cause_allowed": False,
        "supervisor_watchdog_refused": assessed.get("supervisor_watchdog_refused") is True,
        "soak_dut_watchdog_counts_as_supervisor_watchdog": False,
        "condition_id": condition_id,
        "condition_detail": detail,
        "counts_as_start": False,
        "counts_as_pass": False,
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "production_7x24": "NOT_ACCEPTED",
        "binds_clock_start": False,
        "a_72h_pass_is_production_readiness": False,
        "declarations_are_not_a_start": True,
    }


def _founder_probes(l2: Any) -> tuple[list[dict[str, Any]], bool]:
    """In-memory claims. None of them starts the clock."""
    legal = l2.legal_founder_declaration()
    missing = json.loads(json.dumps(legal))
    missing.pop("supervision_policy", None)
    local_only = json.loads(json.dumps(legal))
    local_only["evidence"]["publication"] = "LOCAL_ONLY"
    unknown = json.loads(json.dumps(legal))
    unknown["failure_attribution"]["terminal"] = "unknown root cause"
    unknown["failure_attribution"]["unknown_root_cause_allowed"] = True
    no_watchdog = json.loads(json.dumps(legal))
    no_watchdog["supervisor_watchdog"] = {
        "present": False,
        "kind": "none",
        "crash_recorded_within_seconds": None,
    }
    soak_dut = json.loads(json.dumps(legal))
    soak_dut["supervisor_watchdog"] = {
        "present": True,
        "kind": "stall_watchdog",
        "crash_recorded_within_seconds": 5,
    }
    approval = {"approval_is_a_start": True, "start_registration_present": True}
    specs = (
        ("approval_is_not_a_start", approval, "supervision_policy"),
        ("missing_condition", missing, "supervision_policy"),
        ("local_only", local_only, "public_evidence"),
        ("unknown_root_cause", unknown, "three_way_attribution"),
        ("supervisor_without_watchdog", no_watchdog, "supervision_cadence_and_supervisor_watchdog"),
        ("soak_dut_watchdog_substituted", soak_dut, "supervision_cadence_and_supervisor_watchdog"),
    )
    rows: list[dict[str, Any]] = []
    shape_ok = True
    expected_detail = {
        "approval_is_not_a_start": "not_declared",
        "missing_condition": "not_declared",
        "local_only": "local_only_refused",
        "unknown_root_cause": "unknown_root_cause_refused",
        "supervisor_without_watchdog": "supervisor_watchdog_missing",
        "soak_dut_watchdog_substituted": "soak_dut_watchdog_is_not_supervisor_watchdog",
    }
    for label, claim, condition_id in specs:
        try:
            assessed = l2.assess_founder_start(claim)
        except Exception:
            return [], False
        if not isinstance(assessed, dict):
            return [], False
        row = _founder_probe_row(label, assessed, condition_id)
        detail = expected_detail[label]
        lie = (
            row["approval_is_a_start"] is not False
            or row["conditions_satisfied"] is not False
            or row["counts_as_start"] is not False
            or row["counts_as_pass"] is not False
            or row["can_start_clock"] is not False
            or row["local_only_counts_as_public_evidence"] is not False
            or row["unknown_root_cause_allowed"] is not False
            or row["soak_dut_watchdog_counts_as_supervisor_watchdog"] is not False
            or row["start_registration_present"] is not False
            or row["l2_2_status"] != "NOT_STARTED"
            or row["clock_state"] != "NOT_STARTED"
            or row["production_7x24"] != "NOT_ACCEPTED"
            or row["condition_detail"] != detail
            or assessed.get("approval_is_a_start") is not False
            or assessed.get("can_start_clock") is not False
            or assessed.get("a_72h_pass_is_production_readiness") is not False
        )
        if label == "approval_is_not_a_start":
            lie = lie or row["approval_claimed_as_start"] is not True or row["start_registration_claimed"] is not True
            lie = lie or row["missing_conditions"] != list(l2.FOUNDER_CONDITION_IDS)
        elif label == "missing_condition":
            lie = lie or row["missing_conditions"] != ["supervision_policy"]
        elif label == "local_only":
            lie = lie or row["local_only_refused"] is not True or "public_evidence" not in row["missing_conditions"]
        elif label == "unknown_root_cause":
            lie = lie or row["unknown_root_cause_refused"] is not True
        elif label in {"supervisor_without_watchdog", "soak_dut_watchdog_substituted"}:
            lie = lie or row["supervisor_watchdog_refused"] is not True
        if lie:
            shape_ok = False
        rows.append(row)
    return rows, shape_ok


def _scorer_refuses_founder_report(l2: Any, root: Path) -> bool:
    """True when a forged report cannot relabel the approval as a start or a PASS."""
    fixture = root / FIXTURE_RELATIVE
    if not fixture.is_file():
        return False
    try:
        honest = l2.score(l2.load_capture(fixture))
    except Exception:
        return False
    if not isinstance(honest, dict) or not isinstance(honest.get("founder_start_conditions"), dict):
        return False
    if honest["founder_start_conditions"].get("conditions_satisfied") is not False:
        return False
    if honest["founder_start_conditions"].get("approval_is_a_start") is not False:
        return False

    def names_for(**edits: Any) -> set[str]:
        forged = json.loads(json.dumps(honest))
        block = forged["founder_start_conditions"]
        for key, value in edits.items():
            if key == "l2_2_status":
                forged["l2_2_status"] = value
            elif key == "production_7x24":
                forged["production_7x24"] = value
            elif key in GATE_KEYS:
                forged["gates"][key] = value
            elif key.startswith("condition:"):
                condition_id, field = key.split(":", 2)[1:]
                for item in block["conditions"]:
                    if item.get("id") == condition_id:
                        item[field] = value
            else:
                block[key] = value
        return set(l2.validate_report(forged))

    approval = names_for(
        approval_is_a_start=True,
        conditions_satisfied=True,
        l2_2_status="PASS",
        production_7x24="ACCEPTED",
        can_start_clock=True,
    )
    if not {
        "approval_is_not_a_start",
        "founder_conditions_missing",
        "forged_pass",
        "production_claim",
        "forged_clock_start",
    } <= approval:
        return False
    missing = names_for(conditions_satisfied=True, can_accept_l2_2=True)
    if "founder_conditions_missing" not in missing or "forged_accept" not in missing:
        return False
    local_only = names_for(
        **{
            "local_only_counts_as_public_evidence": True,
            "conditions_satisfied": True,
            "condition:public_evidence:satisfied": True,
            "condition:public_evidence:detail": "local_only_refused",
        }
    )
    if "local_only_refused" not in local_only:
        return False
    unknown = names_for(
        **{
            "unknown_root_cause_allowed": True,
            "conditions_satisfied": True,
            "condition:three_way_attribution:satisfied": True,
            "condition:three_way_attribution:detail": "unknown_root_cause_refused",
        }
    )
    if "unknown_root_cause_refused" not in unknown:
        return False
    watchdog = names_for(
        **{
            "soak_dut_watchdog_counts_as_supervisor_watchdog": True,
            "conditions_satisfied": True,
            "condition:supervision_cadence_and_supervisor_watchdog:satisfied": True,
            "condition:supervision_cadence_and_supervisor_watchdog:detail": "soak_dut_watchdog_is_not_supervisor_watchdog",
        }
    )
    return "supervisor_watchdog_required" in watchdog


def _blank_templates(
    root: Path,
    *,
    decision_path: Path | None = None,
    checklist_path: Path | None = None,
) -> tuple[str, bool, bool]:
    """Return (detail or empty, templates_unfilled, bands_documented).

    A filled start line is not this pass posting a start. The placeholder
    shape in the blank template does not count as a registration.
    """
    decision_path = decision_path or (root / DECISION_RELATIVE)
    checklist_path = checklist_path or (root / CHECKLIST_RELATIVE)
    if not decision_path.is_file() or not checklist_path.is_file():
        return "templates_missing", False, False
    try:
        decision = decision_path.read_text(encoding="utf-8")
        checklist = checklist_path.read_text(encoding="utf-8")
    except OSError:
        return "templates_missing", False, False
    bands = "13s through 300s" in checklist and "> 300" in checklist
    try:
        import l2_2_score as l2
    except Exception:
        l2 = None
    posted = False
    if l2 is not None and (
        l2.start_registration_line_present(decision) or l2.start_registration_line_present(checklist)
    ):
        posted = True
    if posted:
        return "start_registration_is_not_this_pass", False, bands
    decision_blank = classify_start_decision(decision).get("ok") is True
    checklist_blank = classify_r2(checklist).get("ok") is True
    if decision_blank and checklist_blank:
        return "", True, bands
    return "templates_not_blank", False, bands


def _closed_founder(detail: str, **extra: Any) -> dict[str, Any]:
    """Founder-condition row. The approval is recorded and is not a start."""
    try:
        import l2_2_score as l2

        base = l2.assess_founder_start(None)
    except Exception:
        base = {
            "rule": "five_founder_conditions_before_start",
            "approval_exists": True,
            "approval_conditional": True,
            "approval_issue": 9,
            "approval_comment_id": 6761044915,
            "approval_utc": "2026-11-10T06:50:14Z",
            "approval_target_pr": 12,
            "approval_is_a_start": False,
            "approval_is_a_pass": False,
            "approval_claimed_as_start": False,
            "approval_without_conditions_is_a_start": False,
            "approval_without_start_registration_is_a_start": False,
            "start_registration_present": False,
            "start_registration_posted_to_issue_9": False,
            "start_registration_claimed": False,
            "conditions_satisfied": False,
            "missing_conditions": [
                "supervision_policy",
                "supervision_cadence_and_supervisor_watchdog",
                "public_evidence",
                "three_way_attribution",
                "not_production_7x24",
            ],
            "local_only_counts_as_public_evidence": False,
            "local_only_refused": False,
            "unknown_root_cause_allowed": False,
            "unknown_root_cause_refused": False,
            "soak_dut_watchdog_counts_as_supervisor_watchdog": False,
            "supervisor_watchdog_refused": False,
            "supervisor_watchdog_kind_required": "other_process",
            "supervision_write_max_seconds": 600,
            "supervisor_watchdog_max_seconds": 10,
            "yellow_min_seconds": 13.0,
            "yellow_max_seconds": 300.0,
            "red_exclusive_min_seconds": 300.0,
            "clock_required": "monotonic",
            "a_72h_pass_is_production_readiness": False,
            "production_7x24": "NOT_ACCEPTED",
            "can_start_clock": False,
            "can_accept_l2_2": False,
            "can_close_l2_2": False,
            "binds_clock_start": False,
            "declarations_are_not_a_start": True,
            "l2_2_status": "NOT_STARTED",
            "clock_state": "NOT_STARTED",
            "clock_effect": "none",
            "conditions": [],
        }
    refused = extra.get("refused_claims")
    if not isinstance(refused, list):
        refused = []
    base["ok"] = extra.get("ok") is True
    base["tool"] = "scripts/l2_2_score.py"
    base["templates_unfilled"] = extra.get("templates_unfilled") is True
    base["blank_template_documents_bands"] = extra.get("blank_template_documents_bands") is True
    base["soak_dut_watchdog_present"] = True
    base["soak_dut_watchdog_tool"] = "scripts/stall_watchdog.py"
    base["scaffold_sha256sums_is_soak_evidence"] = False
    base["refused_claims"] = refused
    base["approval_is_a_start"] = False
    base["approval_is_a_pass"] = False
    base["approval_without_conditions_is_a_start"] = False
    base["approval_without_start_registration_is_a_start"] = False
    base["start_registration_present"] = False
    base["start_registration_posted_to_issue_9"] = False
    base["conditions_satisfied"] = False
    base["local_only_counts_as_public_evidence"] = False
    base["unknown_root_cause_allowed"] = False
    base["soak_dut_watchdog_counts_as_supervisor_watchdog"] = False
    base["a_72h_pass_is_production_readiness"] = False
    base["production_7x24"] = "NOT_ACCEPTED"
    base["can_start_clock"] = False
    base["can_accept_l2_2"] = False
    base["can_close_l2_2"] = False
    base["binds_clock_start"] = False
    base["declarations_are_not_a_start"] = True
    base["l2_2_status"] = "NOT_STARTED"
    base["clock_state"] = "NOT_STARTED"
    base["clock_effect"] = "none"
    base["soak_launched"] = False
    base["documented_soak_argv_executed"] = False
    base["detail"] = detail if detail in FOUNDER_CLOSED_DETAILS else "probe_failed"
    if base["conditions_satisfied"] is not False:
        base["ok"] = False
        base["detail"] = "probe_failed"
    return base


def _check_founder_start(
    root: Path,
    *,
    decision_path: Path | None = None,
    checklist_path: Path | None = None,
) -> dict[str, Any]:
    """Record the conditional approval and prove it is not a start.

    The committed templates stay unfilled. This check does not post an
    L2-2 START line and does not launch soak_2h.py.
    """
    template_detail, templates_unfilled, bands = _blank_templates(
        root,
        decision_path=decision_path,
        checklist_path=checklist_path,
    )
    try:
        import l2_2_score as l2
    except Exception:
        return _closed_founder(
            "scorer_import",
            templates_unfilled=False,
            blank_template_documents_bands=False,
            refused_claims=[],
        )
    if not callable(getattr(l2, "assess_founder_start", None)) or not callable(getattr(l2, "validate_report", None)):
        return _closed_founder("scorer_import", refused_claims=[])
    refused, probes_ok = _founder_probes(l2)
    forged_ok = _scorer_refuses_founder_report(l2, root) if probes_ok else False
    if not probes_ok:
        detail = "probe_failed"
    elif template_detail:
        detail = template_detail
    elif not forged_ok:
        detail = "forged_founder_not_refused"
    else:
        detail = "approval_recorded_not_a_start"
    return _closed_founder(
        detail,
        ok=detail == "approval_recorded_not_a_start",
        templates_unfilled=templates_unfilled,
        blank_template_documents_bands=bands,
        refused_claims=refused,
    )


def _founder_preflight_violations(row: Any) -> list[str]:
    """Reject a preflight row that treats the approval as a start or a PASS."""
    violations: list[str] = []
    if not isinstance(row, dict):
        return ["founder_start_conditions"]
    if row.get("tool") != "scripts/l2_2_score.py":
        violations.append("founder_start_conditions")
    if row.get("approval_is_a_start") is not False or row.get("approval_is_a_pass") is not False:
        violations.append("approval_is_not_a_start")
    if row.get("approval_without_conditions_is_a_start") is not False:
        violations.append("approval_is_not_a_start")
    if row.get("approval_without_start_registration_is_a_start") is not False:
        violations.append("approval_is_not_a_start")
    if row.get("start_registration_present") is not False or row.get("start_registration_posted_to_issue_9") is not False:
        violations.append("approval_is_not_a_start")
    if row.get("conditions_satisfied") is not False:
        violations.append("founder_conditions_missing")
    if row.get("local_only_counts_as_public_evidence") is not False or row.get("local_only_refused") is not False:
        violations.append("local_only_refused")
    if row.get("unknown_root_cause_allowed") is not False or row.get("unknown_root_cause_refused") is not False:
        violations.append("unknown_root_cause_refused")
    if row.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is not False:
        violations.append("supervisor_watchdog_required")
    if row.get("supervisor_watchdog_refused") is not False:
        violations.append("supervisor_watchdog_required")
    if row.get("a_72h_pass_is_production_readiness") is not False or row.get("production_7x24") != "NOT_ACCEPTED":
        violations.append("production_claim")
    if row.get("binds_clock_start") is not False or row.get("soak_launched") is not False:
        violations.append("approval_is_not_a_start")
    if row.get("documented_soak_argv_executed") is not False:
        violations.append("argv_executed")
    if row.get("clock_effect") != "none":
        violations.append("clock_effect")
    if row.get("l2_2_status") != "NOT_STARTED":
        violations.append("status")
    if row.get("clock_state") != "NOT_STARTED":
        violations.append("clock_state")
    if row.get("declarations_are_not_a_start") is not True:
        violations.append("approval_is_not_a_start")
    if row.get("scaffold_sha256sums_is_soak_evidence") is not False:
        violations.append("local_only_refused")
    if row.get("soak_dut_watchdog_tool") != "scripts/stall_watchdog.py" or row.get("soak_dut_watchdog_present") is not True:
        violations.append("supervisor_watchdog_required")
    for key in GATE_KEYS:
        if row.get(key) is not False:
            violations.append("forged_" + key)
    missing = row.get("missing_conditions")
    if missing != [
        "supervision_policy",
        "supervision_cadence_and_supervisor_watchdog",
        "public_evidence",
        "three_way_attribution",
        "not_production_7x24",
    ]:
        violations.append("founder_conditions_missing")
    conditions = row.get("conditions")
    if not isinstance(conditions, list):
        violations.append("founder_start_conditions")
    else:
        ids = [item.get("id") if isinstance(item, dict) else None for item in conditions]
        if ids != [
            "supervision_policy",
            "supervision_cadence_and_supervisor_watchdog",
            "public_evidence",
            "three_way_attribution",
            "not_production_7x24",
        ]:
            violations.append("founder_start_conditions")
        else:
            for item in conditions:
                if item.get("satisfied") is not False or item.get("declared") is not False or item.get("detail") != "not_declared":
                    violations.append("founder_conditions_missing")
    claims = row.get("refused_claims")
    if not isinstance(claims, list):
        violations.append("founder_start_conditions")
    else:
        labels = [item.get("label") if isinstance(item, dict) else None for item in claims]
        if row.get("detail") != "scorer_import" and labels != list(FOUNDER_PROBE_LABELS):
            violations.append("founder_start_conditions")
        elif row.get("detail") == "scorer_import" and claims:
            violations.append("founder_start_conditions")
        else:
            expected_detail = {
                "approval_is_not_a_start": "not_declared",
                "missing_condition": "not_declared",
                "local_only": "local_only_refused",
                "unknown_root_cause": "unknown_root_cause_refused",
                "supervisor_without_watchdog": "supervisor_watchdog_missing",
                "soak_dut_watchdog_substituted": "soak_dut_watchdog_is_not_supervisor_watchdog",
            }
            for item in claims:
                if (
                    item.get("approval_is_a_start") is not False
                    or item.get("conditions_satisfied") is not False
                    or item.get("counts_as_start") is not False
                    or item.get("counts_as_pass") is not False
                    or item.get("can_start_clock") is not False
                    or item.get("local_only_counts_as_public_evidence") is not False
                    or item.get("unknown_root_cause_allowed") is not False
                    or item.get("soak_dut_watchdog_counts_as_supervisor_watchdog") is not False
                    or item.get("start_registration_present") is not False
                    or item.get("l2_2_status") != "NOT_STARTED"
                    or item.get("clock_state") != "NOT_STARTED"
                    or item.get("production_7x24") != "NOT_ACCEPTED"
                    or item.get("a_72h_pass_is_production_readiness") is not False
                    or item.get("condition_detail") != expected_detail.get(item.get("label"))
                ):
                    violations.append("founder_conditions_missing")
                if item.get("label") == "local_only" and item.get("local_only_refused") is not True:
                    violations.append("local_only_refused")
                if item.get("label") == "unknown_root_cause" and item.get("unknown_root_cause_refused") is not True:
                    violations.append("unknown_root_cause_refused")
                if item.get("label") in {"supervisor_without_watchdog", "soak_dut_watchdog_substituted"} and (
                    item.get("supervisor_watchdog_refused") is not True
                ):
                    violations.append("supervisor_watchdog_required")
                if item.get("label") == "approval_is_not_a_start" and item.get("approval_claimed_as_start") is not True:
                    violations.append("approval_is_not_a_start")
    if row.get("detail") not in FOUNDER_CLOSED_DETAILS:
        violations.append("founder_start_conditions")
    if row.get("ok") is True and row.get("detail") != "approval_recorded_not_a_start":
        violations.append("founder_start_conditions")
    if row.get("ok") is True and row.get("templates_unfilled") is not True:
        violations.append("founder_start_conditions")
    if not isinstance(row.get("ok"), bool):
        violations.append("founder_start_conditions")
    try:
        import l2_2_score as l2

        violations.extend(l2._founder_block_violations(row))
    except Exception:
        violations.append("founder_start_conditions")
    return violations


def _refuses_forged(validate, report: dict[str, Any], **edits: Any) -> bool:
    forged = json.loads(json.dumps(report))
    for key, value in edits.items():
        if key in GATE_KEYS:
            forged["gates"][key] = value
        else:
            forged[key] = value
    violations = validate(forged)
    return bool(violations)


def _check_scorer(root: Path) -> dict[str, Any]:
    fixture = root / FIXTURE_RELATIVE
    if not fixture.is_file():
        return {"ok": False, "status": "withheld", "gates_false": False, "detail": "fixture_missing"}
    try:
        import l2_2_score as l2

        captured = l2.load_capture(fixture)
        scored = l2.score(captured)
    except Exception as exc:
        return {
            "ok": False,
            "status": "withheld",
            "gates_false": False,
            "detail": f"scorer:{type(exc).__name__}",
        }
    gates = scored.get("gates") if isinstance(scored.get("gates"), dict) else {}
    status = scored.get("l2_2_status")
    gates_false = all(gates.get(key) is False for key in GATE_KEYS)
    status_safe = status in {"NOT_STARTED", "INCOMPLETE"}
    forged_ok = (
        _refuses_forged(l2.validate_report, scored, l2_2_status="PASS")
        and _refuses_forged(l2.validate_report, scored, can_start_clock=True)
        and _refuses_forged(l2.validate_report, scored, can_accept_l2_2=True)
        and _refuses_forged(l2.validate_report, scored, can_close_l2_2=True)
    )
    clean = l2.validate_report(scored) == []
    ok = gates_false and status_safe and forged_ok and clean and scored.get("production_7x24") == "NOT_ACCEPTED"
    return {
        "ok": ok,
        "status": status if status_safe and gates_false else "withheld",
        "gates_false": gates_false,
        "forged_pass_rejected": _refuses_forged(l2.validate_report, scored, l2_2_status="PASS"),
        "forged_clock_rejected": _refuses_forged(l2.validate_report, scored, can_start_clock=True),
        "forged_accept_rejected": _refuses_forged(l2.validate_report, scored, can_accept_l2_2=True),
        "forged_close_rejected": _refuses_forged(l2.validate_report, scored, can_close_l2_2=True),
        "detail": "refused" if ok else "scorer_would_overclaim",
    }


def _l2_4() -> dict[str, Any]:
    try:
        import l2_2_score as l2

        return dict(l2.L2_4_CROSSLINK)
    except Exception:
        return {
            "status": "INCOMPLETE",
            "window": "2026-11-03..06",
            "pr": "https://github.com/shugnn/AIStudioOS-Grok/pull/11",
            "tip": "931758cb7487d8c8ac1697f1b3ad1e2fa7610ef6",
            "relitigated": False,
        }


def _gates() -> dict[str, Any]:
    return {
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "can_start_clock": False,
        "close_policy": (
            "This preflight never accepts L2-2, never closes it, and never starts the 72h clock. "
            "A check that holds means the not-started scaffold is intact. "
            "It is not permission to launch soak_2h.py. "
            "Production 7x24 stays NOT ACCEPTED."
        ),
    }


def _assemble(checks: dict[str, Any]) -> dict[str, Any]:
    failures = [
        f"{name}:{checks[name].get('detail', 'failed')}"
        for name in CHECK_ORDER
        if checks[name].get("ok") is not True
    ]
    return {
        "schema": SCHEMA,
        "report_kind": "offline_preflight",
        "evidence_class": "scaffold",
        "label": "scaffold",
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "soak_launched": False,
        "interactive_tasks_registered": False,
        "production_7x24": "NOT_ACCEPTED",
        "product_l2_task_split": "NOT_STARTED",
        "business_verdict": "UNSCORED",
        "verified": False,
        "supervision_verified": False,
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
        "not_started_scaffold_intact": not failures,
        "operator_note": OPERATOR_NOTE,
        "gates": _gates(),
        "l2_4": _l2_4(),
        "ubuntu_24h_specimen": checks["ubuntu_24h_specimen"],
        "non_additivity": checks["non_additivity"],
        "process_continuity": checks["process_continuity"],
        "founder_start_conditions": checks["founder_start_conditions"],
        "checks": checks,
        "failures": failures,
        "documented_soak_argv": list(DOCUMENTED_ARGV),
        "documented_soak_argv_executed": False,
        "next_steps": list(NEXT_STEPS),
        "source": {
            "collector": "scripts/l2_2_preflight.py",
            "collector_mode": "offline_preflight",
        },
    }


def _failed_checks(detail: str) -> dict[str, Any]:
    return {name: {"ok": False, "detail": detail} for name in CHECK_ORDER}


def preflight(
    root: Path | None = None,
    *,
    checklist_path: Path | None = None,
    stop_path: Path | None = None,
    sums_path: Path | None = None,
    start_decision_path: Path | None = None,
    metrics_path: Path | None = None,
) -> dict[str, Any]:
    """Build an honest NOT_STARTED report. Does not launch soak or write the stop file."""
    repo = (root or ROOT).resolve()
    checklist = checklist_path or (repo / CHECKLIST_RELATIVE)
    decision = start_decision_path or (repo / DECISION_RELATIVE)
    stop = stop_path or default_stop_path(repo)
    sums = sums_path or (repo / SUMS_RELATIVE)
    metrics = metrics_path or (repo / UBUNTU_24H_METRICS)
    try:
        checks = {
            "scaffold_files": _check_files(repo),
            "evidence_sums": _check_sums(repo, sums),
            "contract": _check_contract(repo),
            "soak_flags": _check_soak_flags(),
            "r2_checklist": _check_r2(checklist),
            "start_decision": _check_start_decision(decision),
            "emergency_stop": _check_stop(stop, repo),
            "gap_logger": _check_gap_logger(),
            "supervision_monitor": _check_monitor(),
            "stall_watchdog": _check_stall_watchdog(),
            "ubuntu_24h_specimen": _check_ubuntu_specimen(metrics),
            "non_additivity": _check_non_additivity(repo),
            "process_continuity": _check_process_continuity(repo),
            "founder_start_conditions": _check_founder_start(
                repo,
                decision_path=decision,
                checklist_path=checklist,
            ),
            "scorer_refuses": _check_scorer(repo),
        }
    except Exception as exc:
        checks = _failed_checks(f"preflight:{type(exc).__name__}")
    return _assemble(checks)


def _forbid_true_gates(node: Any, violations: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in GATE_KEYS and value is not False:
                violations.append("forged_" + key)
            else:
                _forbid_true_gates(value, violations)
    elif isinstance(node, list):
        for item in node:
            _forbid_true_gates(item, violations)


def validate_report(report: dict[str, Any]) -> list[str]:
    """Reject any report that could be read as a clock start, accept, or close."""
    violations: list[str] = []
    if report.get("schema") != SCHEMA:
        violations.append("schema")
    if report.get("report_kind") != "offline_preflight":
        violations.append("report_kind")
    if report.get("l2_2_status") != "NOT_STARTED":
        violations.append("status")
    if report.get("clock_state") != "NOT_STARTED":
        violations.append("clock_state")
    if report.get("clock_effect") != "none":
        violations.append("clock_effect")
    if report.get("soak_launched") is not False:
        violations.append("soak_launched")
    if report.get("documented_soak_argv_executed") is not False:
        violations.append("argv_executed")
    if report.get("interactive_tasks_registered") is not False:
        violations.append("interactive_tasks")
    if report.get("production_7x24") != "NOT_ACCEPTED":
        violations.append("production_claim")
    if report.get("product_l2_task_split") != "NOT_STARTED":
        violations.append("product_l2_claim")
    if report.get("verified") is not False:
        violations.append("verified_claim")
    if report.get("supervision_verified") is not False:
        violations.append("supervision_verified_claim")
    if report.get("business_verdict") != "UNSCORED":
        violations.append("business_verdict")
    if report.get("gate_result") != "NOT_A_GATE":
        violations.append("gate_result")
    if report.get("exit_0_is_gate_pass") is not False:
        violations.append("exit_0_claim")
    if report.get("label") != "scaffold" or report.get("evidence_class") != "scaffold":
        violations.append("label")
    l2_4 = report.get("l2_4") if isinstance(report.get("l2_4"), dict) else {}
    if l2_4.get("status") != "INCOMPLETE" or l2_4.get("relitigated") is not False:
        violations.append("l2_4_crosslink")
    gates = report.get("gates") if isinstance(report.get("gates"), dict) else {}
    for key in GATE_KEYS:
        if gates.get(key) is not False:
            violations.append("forged_" + key)
    _forbid_true_gates(report, violations)
    checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
    if tuple(checks) != CHECK_ORDER:
        violations.append("checks")
    else:
        for name in CHECK_ORDER:
            if not isinstance(checks[name].get("ok"), bool):
                violations.append("check_ok")
    failures = report.get("failures")
    intact = report.get("not_started_scaffold_intact")
    if not isinstance(failures, list):
        violations.append("failures")
    elif intact is True and failures:
        violations.append("intact_with_failures")
    elif intact is False and not failures:
        violations.append("failures_missing")
    elif intact not in {True, False}:
        violations.append("intact")
    decision = ""
    r2 = checks.get("r2_checklist") if isinstance(checks.get("r2_checklist"), dict) else {}
    if isinstance(r2, dict):
        decision = str(r2.get("start_decision") or "")
    sums = checks.get("evidence_sums") if isinstance(checks.get("evidence_sums"), dict) else {}
    if isinstance(sums, dict) and sums.get("binds_clock_start") is True:
        violations.append("sums_imply_start")
    if decision in {"given", "started", "approved"}:
        violations.append("r2_implies_start")
    decided = checks.get("start_decision") if isinstance(checks.get("start_decision"), dict) else {}
    if isinstance(decided, dict):
        decided_value = str(decided.get("start_decision") or "")
        if decided_value in {"given", "started", "approved"}:
            violations.append("start_decision_implies_start")
        if decided.get("binds_clock_start") is True:
            violations.append("start_decision_implies_start")
        if decided.get("detail") == "forged_claim" and decided.get("ok") is True:
            violations.append("start_decision_implies_start")
    stall = checks.get("stall_watchdog") if isinstance(checks.get("stall_watchdog"), dict) else {}
    if isinstance(stall, dict):
        if stall.get("binds_clock_start") is True or stall.get("implies_l2_2_acceptance") is True:
            violations.append("stall_implies_start")
        if stall.get("implies_72h_pass") is True or stall.get("gap_implies_soak_complete") is True:
            violations.append("stall_implies_start")
        if stall.get("ubuntu_24h_used_as_dut") is True or stall.get("default_summary_used") is True:
            violations.append("stall_ubuntu_dut")
        if stall.get("repo_alert_written") is True or stall.get("alert_left_in_repo") is True:
            violations.append("stall_alert_in_repo")
        if stall.get("gap_appended") is True:
            violations.append("stall_gap_appended")
        if stall.get("clock_effect") != "none":
            violations.append("clock_effect")
        if stall.get("clock_state") != "NOT_STARTED":
            violations.append("clock_state")
        if stall.get("l2_2_status") != "NOT_STARTED":
            violations.append("status")
        if stall.get("production_7x24") != "NOT_ACCEPTED":
            violations.append("production_claim")
        for key in GATE_KEYS:
            if stall.get(key) is not False:
                violations.append("forged_" + key)
        if stall.get("ok") is True:
            shape_ok = (
                stall.get("fresh_stalled") is False
                and stall.get("stale_stalled") is True
                and stall.get("fresh_exit") == 0
                and stall.get("stale_exit") == 1
                and stall.get("fresh_gap_band") == "ok"
                and stall.get("stale_gap_band") == "red"
                and stall.get("action") == "synthetic_mtime"
                and stall.get("dut") == "synthetic_temp_summary"
                and stall.get("detail") == "synthetic_fresh_vs_stale"
                and stall.get("gap_appended") is False
            )
            if not shape_ok:
                violations.append("stall_classification")
    specimen = checks.get("ubuntu_24h_specimen")
    top_specimen = report.get("ubuntu_24h_specimen")
    violations.extend(_specimen_violations(specimen))
    violations.extend(_specimen_violations(top_specimen))
    if specimen != top_specimen:
        violations.append("ubuntu_24h_specimen_mismatch")
    additive = checks.get("non_additivity")
    top_additive = report.get("non_additivity")
    violations.extend(_non_additivity_violations(additive))
    violations.extend(_non_additivity_violations(top_additive))
    if additive != top_additive:
        violations.append("non_additivity_mismatch")
    continuity = checks.get("process_continuity")
    top_continuity = report.get("process_continuity")
    violations.extend(_process_continuity_violations(continuity))
    violations.extend(_process_continuity_violations(top_continuity))
    if continuity != top_continuity:
        violations.append("process_continuity_mismatch")
    founder = checks.get("founder_start_conditions")
    top_founder = report.get("founder_start_conditions")
    violations.extend(_founder_preflight_violations(founder))
    violations.extend(_founder_preflight_violations(top_founder))
    if founder != top_founder:
        violations.append("founder_start_conditions_mismatch")
    if not isinstance(report.get("next_steps"), list) or not report.get("next_steps"):
        violations.append("next_steps")
    if "not a start decision" not in str(report.get("operator_note")):
        violations.append("operator_note")
    return violations


def _refusal(detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "refusing_overclaim",
        "detail": detail,
        "schema": SCHEMA,
        "l2_2_status": "NOT_STARTED",
        "clock_state": "NOT_STARTED",
        "clock_effect": "none",
        "soak_launched": False,
        "production_7x24": "NOT_ACCEPTED",
        "gate_result": "NOT_A_GATE",
        "exit_0_is_gate_pass": False,
        "gates": {
            "can_accept_l2_2": False,
            "can_close_l2_2": False,
            "can_start_clock": False,
        },
        "operator_note": OPERATOR_NOTE,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None, help="write the report here; default is stdout only")
    ap.add_argument("--root", type=Path, default=None, help="repo root to inspect (default: this repo)")
    args = ap.parse_args(argv)
    report = preflight(args.root)
    violations = validate_report(report)
    if violations:
        text = json.dumps(_refusal(",".join(violations)), indent=2, ensure_ascii=False) + "\n"
        print(text, end="")
        return 2
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(text, end="")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0 if report["not_started_scaffold_intact"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
