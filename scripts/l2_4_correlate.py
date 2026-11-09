#!/usr/bin/env python3
"""L2-4 Windows Terminal time-correlation helper.

Reads a capture bundle (schema aistudioos-grok.l2-4.capture.v1) and writes an
honest report. Time overlap is not causation. This tool never emits L2-4 PASS
and never accepts production 7x24.

Exit 0: an honest INCOMPLETE report was produced.
Exit 2: the capture or the report failed validation.

  python3 scripts/l2_4_correlate.py --capture tests/fixtures/l2_4/scaffold_strong_time_overlap.json
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_CAPTURE = "aistudioos-grok.l2-4.capture.v1"
SCHEMA_REPORT = "aistudioos-grok.l2-4.report.v1"
DEFAULT_WINDOW_S = 600.0
STRONG_MIN_EVENTS = 3
STRONG_MIN_RATIO = 0.7
MODERATE_MIN_RATIO = 0.4

WT_APP_RE = re.compile(r"(?i)(^|[\\/])(windowsterminal|wt)\.exe$")
REBOOT_EVENT_IDS = {12, 41, 1074, 6005, 6006, 6008}
BAD_WATCH_TARGETS = {"soak_summary", "summary.jsonl", "ended_experiment"}
CONSOLE_INTERPRETERS = {"python.exe", "py.exe"}


class CaptureError(ValueError):
    """Capture bundle is missing, mislabeled, or not safe to score."""


def parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise CaptureError(f"{field}: timestamp must be an ISO-8601 string")
    text = value.strip()
    if not text:
        raise CaptureError(f"{field}: empty timestamp")
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise CaptureError(f"{field}: unparseable timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise CaptureError(
            f"{field}: naive timestamp rejected (need UTC offset or Z): {value!r}"
        )
    return parsed.astimezone(timezone.utc)


def utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exe_name(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.lower()


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def load_capture(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaptureError(f"unreadable capture: {path}: {exc}") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CaptureError(f"capture is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise CaptureError("capture root must be an object")
    validate_capture(doc)
    return doc


def validate_capture(doc: dict[str, Any]) -> None:
    if doc.get("schema") != SCHEMA_CAPTURE:
        raise CaptureError(f"schema must be {SCHEMA_CAPTURE}")
    evidence = doc.get("evidence_class")
    if evidence not in {"scaffold", "host_capture"}:
        raise CaptureError("evidence_class must be scaffold or host_capture")
    if doc.get("synthetic") is True and evidence != "scaffold":
        raise CaptureError("synthetic capture must be evidence_class scaffold")
    if evidence == "scaffold" and doc.get("synthetic") is not True:
        raise CaptureError("scaffold capture must set synthetic true")
    for key in ("tasks", "wt_errors", "reboots"):
        if not isinstance(doc.get(key), list):
            raise CaptureError(f"{key} must be a list")
    for optional in ("task_runs", "runner_artifacts"):
        if optional in doc and not isinstance(doc[optional], list):
            raise CaptureError(f"{optional} must be a list")
    for index, task in enumerate(doc["tasks"]):
        if not isinstance(task, dict):
            raise CaptureError(f"tasks[{index}] must be an object")
        if not isinstance(task.get("task_name"), str) or not task["task_name"].strip():
            raise CaptureError(f"tasks[{index}].task_name required")
        if "run_times_utc" in task:
            if not isinstance(task["run_times_utc"], list):
                raise CaptureError(f"tasks[{index}].run_times_utc must be a list")
            for ts in task["run_times_utc"]:
                parse_utc(ts, field=f"tasks[{index}].run_times_utc")
        if not _is_blank(task.get("last_run_time")):
            parse_utc(task.get("last_run_time"), field=f"tasks[{index}].last_run_time")
    _require_events(doc["wt_errors"], "wt_errors", expected_id=1000, require_wt_app=True)
    _require_events(doc["reboots"], "reboots", allowed_ids=REBOOT_EVENT_IDS)
    if "task_runs" in doc:
        _require_events(doc["task_runs"], "task_runs")
    if "runner_artifacts" in doc:
        for index, row in enumerate(doc["runner_artifacts"]):
            if not isinstance(row, dict):
                raise CaptureError(f"runner_artifacts[{index}] must be an object")
            parse_utc(row.get("utc"), field=f"runner_artifacts[{index}].utc")
    process_tree = doc.get("process_tree", {"available": False, "links": []})
    if not isinstance(process_tree, dict):
        raise CaptureError("process_tree must be an object")
    if process_tree.get("available") is True:
        links = process_tree.get("links")
        if not isinstance(links, list) or not links:
            raise CaptureError("process_tree.available requires a non-empty links list")
        for index, link in enumerate(links):
            if not isinstance(link, dict):
                raise CaptureError(f"process_tree.links[{index}] must be an object")
            if _is_blank(link.get("parent_image")) or _is_blank(link.get("child_image")):
                raise CaptureError(
                    f"process_tree.links[{index}] needs parent_image and child_image"
                )


def _require_events(
    rows: list[Any],
    field: str,
    *,
    expected_id: int | None = None,
    allowed_ids: set[int] | None = None,
    require_wt_app: bool = False,
) -> None:
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CaptureError(f"{field}[{index}] must be an object")
        parse_utc(row.get("utc"), field=f"{field}[{index}].utc")
        event_id = row.get("event_id")
        if expected_id is not None or allowed_ids is not None:
            if not isinstance(event_id, int):
                raise CaptureError(f"{field}[{index}].event_id must be an int")
        if expected_id is not None and event_id != expected_id:
            raise CaptureError(f"{field}[{index}].event_id must be {expected_id}")
        if allowed_ids is not None and event_id not in allowed_ids:
            raise CaptureError(f"{field}[{index}].event_id {event_id} is not a reboot id")
        if require_wt_app:
            app = row.get("faulting_application")
            if not isinstance(app, str) or WT_APP_RE.search(app.strip()) is None:
                raise CaptureError(
                    f"{field}[{index}].faulting_application must be WindowsTerminal.exe or wt.exe"
                )


def _history_unavailable(doc: dict[str, Any]) -> bool:
    history = doc.get("task_history")
    return isinstance(history, dict) and history.get("available") is False


def _anchors_from_capture(doc: dict[str, Any]) -> tuple[list[datetime], str]:
    """Scheduler starts are the duty anchors. Runner files are not a substitute.

    An empty task_runs list is a real zero when history was readable.
    When history is marked unavailable and task_runs is empty, fall through
    so a snapshot run_times_utc list can still be scored.
    """
    runs = doc.get("task_runs")
    if isinstance(runs, list) and not (_history_unavailable(doc) and len(runs) == 0):
        stamps = [parse_utc(row["utc"], field="task_runs") for row in runs]
        return stamps, "task_runs"
    stamps: list[datetime] = []
    for task in doc["tasks"]:
        for ts in task.get("run_times_utc") or []:
            stamps.append(parse_utc(ts, field="run_times_utc"))
    if stamps:
        return stamps, "task_run_times_utc"
    return [], "none"


def _runner_anchors(doc: dict[str, Any]) -> list[datetime]:
    return [parse_utc(row["utc"], field="runner") for row in doc.get("runner_artifacts") or []]


def correlate_timestamps(
    error_times: list[datetime],
    anchor_times: list[datetime],
    window_seconds: float = DEFAULT_WINDOW_S,
) -> dict[str, Any]:
    """Nearest-anchor overlap. Strength never means causation."""
    if window_seconds <= 0:
        raise CaptureError("window_seconds must be positive")
    pairs: list[dict[str, Any]] = []
    deltas: list[float] = []
    matched = 0
    for err in error_times:
        if not anchor_times:
            pairs.append(
                {
                    "error_utc": utc_z(err),
                    "nearest_anchor_utc": None,
                    "abs_delta_seconds": None,
                    "within_window": False,
                }
            )
            continue
        nearest = min(anchor_times, key=lambda stamp: abs((err - stamp).total_seconds()))
        delta = abs((err - nearest).total_seconds())
        deltas.append(delta)
        within = delta <= window_seconds
        if within:
            matched += 1
        pairs.append(
            {
                "error_utc": utc_z(err),
                "nearest_anchor_utc": utc_z(nearest),
                "abs_delta_seconds": round(delta, 3),
                "within_window": within,
            }
        )
    n_err = len(error_times)
    ratio = round(matched / n_err, 4) if n_err else None
    median = round(statistics.median(deltas), 3) if deltas else None
    strength = _strength(n_err, matched, ratio, median, window_seconds, has_anchors=bool(anchor_times))
    return {
        "method": "nearest_anchor_abs_delta",
        "window_seconds": window_seconds,
        "error_count": n_err,
        "anchor_count": len(anchor_times),
        "matched_within_window": matched,
        "match_ratio": ratio,
        "median_abs_delta_seconds": median,
        "strength": strength,
        "pairs": pairs,
    }


def _strength(
    n_err: int,
    matched: int,
    ratio: float | None,
    median: float | None,
    window_seconds: float,
    *,
    has_anchors: bool,
) -> str:
    if n_err == 0:
        return "no_events"
    if not has_anchors:
        return "no_anchor"
    assert ratio is not None
    if (
        n_err >= STRONG_MIN_EVENTS
        and ratio >= STRONG_MIN_RATIO
        and median is not None
        and median <= window_seconds
    ):
        return "strong"
    if matched >= 1 and ratio >= MODERATE_MIN_RATIO:
        return "moderate"
    if matched >= 1:
        return "weak"
    return "none"


def _task_actions(task: dict[str, Any]) -> list[dict[str, Any]]:
    actions = task.get("actions")
    if isinstance(actions, list) and actions:
        return [a for a in actions if isinstance(a, dict)]
    execute = task.get("execute")
    if isinstance(execute, str) and execute.strip():
        return [{"execute": execute, "arguments": task.get("arguments") or ""}]
    return []


def _console_policy(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    violations: list[dict[str, str]] = []
    interactive: list[str] = []
    console_interpreters: list[str] = []
    for task in tasks:
        name = str(task.get("task_name") or "")
        logon = str(task.get("logon_type") or "")
        if logon.lower() in {"interactive", "interactivetoken"}:
            interactive.append(name)
        for action in _task_actions(task):
            execute = str(action.get("execute") or "")
            arguments = str(action.get("arguments") or "")
            exe = _exe_name(execute) if execute else ""
            if exe == "pythonw.exe" or "pythonw.exe" in arguments.lower():
                violations.append(
                    {
                        "task_name": name,
                        "execute": execute,
                        "reason": "founder requires a console window; pythonw is forbidden",
                    }
                )
            elif exe in CONSOLE_INTERPRETERS:
                console_interpreters.append(execute)
    return {
        "pythonw_forbidden": True,
        "violations": violations,
        "interactive_task_names": interactive,
        "console_interpreters": console_interpreters,
    }


def _reboot_residue(tasks: list[dict[str, Any]], reboots: list[dict[str, Any]]) -> dict[str, Any]:
    residue_tasks = []
    for task in tasks:
        state = str(task.get("state") or "")
        empty_next = _is_blank(task.get("next_run_time"))
        if state.lower() == "ready" and empty_next:
            residue_tasks.append(
                {
                    "task_name": task.get("task_name"),
                    "state": state,
                    "next_run_time_empty": True,
                    "last_run_time": task.get("last_run_time"),
                }
            )
    return {
        "detected": bool(residue_tasks),
        "aligned_with_reboot_event": bool(residue_tasks) and bool(reboots),
        "tasks": residue_tasks,
        "reboot_event_count": len(reboots),
    }


def correlate(doc: dict[str, Any], window_seconds: float | None = None) -> dict[str, Any]:
    validate_capture(doc)
    window = float(window_seconds if window_seconds is not None else doc.get("window_seconds") or DEFAULT_WINDOW_S)
    if window <= 0:
        raise CaptureError("window_seconds must be positive")

    error_times = [parse_utc(row["utc"], field="wt_errors") for row in doc["wt_errors"]]
    task_anchors, task_basis = _anchors_from_capture(doc)
    runner_anchors = _runner_anchors(doc)
    task_series = correlate_timestamps(error_times, task_anchors, window)
    runner_series = correlate_timestamps(error_times, runner_anchors, window)

    if task_basis == "task_runs":
        basis = "task_runs"
        primary = task_series
    elif task_anchors:
        basis = task_basis
        primary = task_series
    elif runner_anchors:
        basis = "runner_artifacts_only"
        primary = runner_series
    else:
        basis = "no_anchors"
        primary = task_series

    tasks = doc["tasks"]
    residue = _reboot_residue(tasks, doc["reboots"])
    console = _console_policy(tasks)
    process_tree = doc.get("process_tree") or {"available": False, "links": []}
    process_available = process_tree.get("available") is True and bool(process_tree.get("links"))

    if basis in {"task_runs", "task_run_times_utc"}:
        wake_count = len(task_anchors)
    elif basis == "runner_artifacts_only":
        wake_count = len(runner_anchors)
    else:
        wake_count = 0
    watch = doc.get("supervision_watch_target")
    watch_bad = isinstance(watch, str) and watch.strip() in BAD_WATCH_TARGETS

    host_signal = (
        bool(doc["reboots"])
        or residue["detected"]
        or primary["strength"] in {"strong", "moderate"}
    )
    triage = {
        "business": False,
        "host": host_signal,
        "supervision": watch_bad,
    }
    attribution = [name for name, on in triage.items() if on]

    blockers = [
        "tool_does_not_close_gate",
        "time_correlation_is_not_causation",
        "founder_reapproval_required_before_new_interactive_duty",
    ]
    if doc.get("evidence_class") == "scaffold":
        blockers.append("scaffold_fixture_not_host_evidence")
    if not process_available:
        blockers.append("process_tree_unavailable")
    else:
        blockers.append("process_tree_present_but_causation_not_declared")
    if residue["detected"]:
        blockers.append("tasks_ready_with_empty_next_run_time")
    if residue["detected"] and not doc["reboots"]:
        blockers.append("reboot_event_not_in_capture")
    if console["violations"]:
        blockers.append("pythonw_forbidden")
    if primary["strength"] == "strong":
        blockers.append("strong_time_correlation_unexplained")
    if basis == "runner_artifacts_only" or _history_unavailable(doc):
        blockers.append("scheduler_history_not_in_capture")
    if primary["anchor_count"] == 0:
        blockers.append("no_duty_anchors")
    if not tasks:
        blockers.append("no_task_snapshot")
    if wake_count < 20:
        blockers.append("fewer_than_20_duty_wakes")
    app_err = doc.get("application_error_1000")
    if isinstance(app_err, dict) and app_err.get("truncated") is True:
        blockers.append("wt_error_list_truncated")
    if isinstance(app_err, dict) and app_err.get("query_available") is False:
        blockers.append("application_error_query_failed")

    evidence = doc["evidence_class"]
    report = {
        "schema": SCHEMA_REPORT,
        "evidence_class": evidence,
        "label": "scaffold" if evidence == "scaffold" else "host_capture_unverified",
        "verified": False,
        "l2_4_status": "INCOMPLETE",
        "production_7x24": "NOT_ACCEPTED",
        "business_fail": False,
        "causation": "not_proven",
        "attribution": attribution,
        "triage": triage,
        "correlation": {
            "basis": basis,
            "strength": primary["strength"],
            "wt_vs_task_runs": task_series,
            "wt_vs_runner_artifacts": runner_series,
            "strength_rule": (
                "strong: >=3 WT errors, match_ratio>=0.7, median abs delta<=window; "
                "moderate: match_ratio>=0.4 with >=1 match; "
                "weak: any match below that; none: anchors exist but no match; "
                "no_events / no_anchor otherwise. "
                "Primary basis is scheduler task_runs when present. "
                "Strength is temporal only."
            ),
        },
        "reboot_residue": residue,
        "console_policy": console,
        "process_tree": {
            "available": bool(process_tree.get("available")),
            "link_count": len(process_tree.get("links") or []),
            "status": "present" if process_available else "unavailable",
        },
        "wake_count": wake_count,
        "wake_bar_20_met": wake_count >= 20,
        "application_error_1000": doc.get("application_error_1000") or {"copied_from_capture": False},
        "gates": {
            "can_close_l2_4": False,
            "close_policy": (
                "This tool never closes L2-4. A later founder-approved host run "
                "can be reviewed by the observation track. Production 7x24 stays NOT ACCEPTED."
            ),
            "blockers": blockers,
        },
        "source": {
            "synthetic": doc.get("synthetic") is True,
            "note": doc.get("note"),
            "host": doc.get("host"),
            "git_sha": doc.get("git_sha"),
            "captured_utc": doc.get("captured_utc"),
            "collector": doc.get("collector"),
        },
    }
    violations = validate_report(report)
    if violations:
        raise CaptureError("refusing to emit report: " + ",".join(violations))
    return report


def validate_report(report: dict[str, Any]) -> list[str]:
    """Reject forged closure. Empty list means the report does not over-claim."""
    violations: list[str] = []
    if report.get("schema") != SCHEMA_REPORT:
        violations.append("schema")
    if report.get("production_7x24") != "NOT_ACCEPTED":
        violations.append("production_claim")
    if report.get("l2_4_status") == "PASS":
        violations.append("forged_pass")
    if report.get("l2_4_status") != "INCOMPLETE":
        violations.append("status_not_incomplete")
    if report.get("causation") == "proven":
        violations.append("causation_proven_forbidden")
    if report.get("causation") != "not_proven":
        violations.append("causation")
    if report.get("verified") is not False:
        violations.append("verified_claim")
    gates = report.get("gates") if isinstance(report.get("gates"), dict) else {}
    if gates.get("can_close_l2_4") is not False:
        violations.append("forged_close")
    if report.get("evidence_class") == "scaffold" and gates.get("can_close_l2_4") is True:
        violations.append("scaffold_cannot_close")
    if report.get("evidence_class") not in {"scaffold", "host_capture"}:
        violations.append("evidence_class")
    if report.get("business_fail") is not False:
        violations.append("business_fail_not_supported")
    return violations


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--window-seconds", type=float, default=None)
    args = ap.parse_args(argv)
    try:
        doc = load_capture(args.capture)
        report = correlate(doc, window_seconds=args.window_seconds)
    except CaptureError as exc:
        print(json.dumps({"ok": False, "error": "invalid_capture", "detail": str(exc)}))
        return 2
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(text, end="")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
