#!/usr/bin/env python3
"""Offline readiness check for the L2-2 72h scaffold.

Reads the repo. Parses documented flags. Does not launch soak_2h.py, does not
start the 72h clock, and does not register scheduled tasks.

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
    "Production 7x24 stays NOT ACCEPTED. The observation track accepts or rejects. This preflight does not.",
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
) -> dict[str, Any]:
    """Build an honest NOT_STARTED report. Does not launch soak or write the stop file."""
    repo = (root or ROOT).resolve()
    checklist = checklist_path or (repo / CHECKLIST_RELATIVE)
    decision = start_decision_path or (repo / DECISION_RELATIVE)
    stop = stop_path or default_stop_path(repo)
    sums = sums_path or (repo / SUMS_RELATIVE)
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
