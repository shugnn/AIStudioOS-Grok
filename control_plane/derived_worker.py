"""Execute a job list derived from a goal statement and an input schema.

The product path is derive, then execute, then write deliverables:

1. ``TaskDecomposer.decompose(goal)`` builds the job list from the statement
   and the columns. A task id, a fixture name, and a pre-written dispatch
   are not inputs to that call.
2. Each derived job runs from its ``kind`` and its structured ``inputs``.
   Titles are labels, not a dispatch table.
3. The derived job list is written to ``derived_dispatch.json`` in the
   output directory after derivation. That file is a product output. The
   runner does not read it, or any ``dispatch.json``, to decide what to do.
4. Deliverables for the jobs that ran are written beside that dispatch.
   ``evidence_pack`` records sha256 and byte length of the input and of
   those deliverables. The dispatch then records the evidence file's hash.

This module does not grant or accept L2. L2 remains CONDITIONAL.
Production 7×24 is NOT ACCEPTED. The L2-2 72h clock is NOT STARTED.
It does not invent an observation card and it does not rerun T1 or T2.

Execution rules (closed, offline, no network, no paid API):

``verify_input_schema``
    Header names, in order, must equal ``inputs.columns``.
    When ``inputs.key`` is set, every key is non-blank and unique.
    The input file's sha256 and byte length are computed from its bytes.

``temporal_aggregate``
    Bucket ``inputs.time_column`` by ``inputs.grain`` (``month`` →
    ``YYYY-MM``, ``week`` → ISO ``YYYY-Www``). Sum each name in
    ``inputs.measures`` with ``Decimal``. A row whose time does not parse
    is skipped. An unparseable measure is counted and is not added as zero.
    ``inputs.group_by`` adds a second bucket key when it is not null.

``anomaly_list``
    On each name in ``inputs.columns``: a blank cell is ``missing``.
    A column is numeric when at least 80% of its non-blank cells parse as
    ``Decimal``. On a numeric column, an unparseable cell is ``non_numeric``,
    a value < 0 is ``negative``, and a value above ``median + 3 * MAD`` is
    ``high_outlier`` when at least 4 numbers parse and MAD is not 0.
    Median and MAD use ``statistics.median`` on ``Decimal`` values.

``sla_breach_list``
    There is no duration threshold. A row is one breach, first match:
    start missing or unparseable → ``missing_or_bad_start``; else end blank
    → ``missing_end``; else end unparseable → ``bad_end``; else end < start
    → ``end_before_start``. Group counts use ``inputs.group_by``.

``backlog_aging``
    ``as_of`` is the latest parsed timestamp in ``inputs.open`` and
    ``inputs.close``, not the wall clock. A row with no parseable open is
    skipped. A close that does not parse, or a close before open, is
    inconsistent. A blank close is still open and is aged to ``as_of``.
    Buckets use ``inputs.grain`` of the open time (``all`` when grain is
    null). Ages are whole seconds, truncated toward zero.

``evidence_pack``
    Hash the input and the other job files that were written. Do not hash
    this file, ``derived_dispatch.json``, or ``worklog.json``.

``loan_operations_summary``
    Count every row. Returned means ``inputs.end`` is non-blank.
    Outstanding means that cell is blank. Overdue uses the same comparison
    as ``overdue_list``. ``inputs.category`` and the month of
    ``inputs.time_column`` count every row. The member ranking is
    ``inputs.member`` by count descending, then the id ascending, limited
    to ``inputs.top_n``. The reference date comes from
    ``inputs.reference_date``. It is not a built-in calendar date.

``overdue_list``
    A row is overdue when ``inputs.end`` is blank and
    (``inputs.reference_date`` − ``inputs.start``) in whole days is greater
    than ``inputs.duration``. Equal to the duration is not overdue. A blank
    or unparseable start or duration is not overdue. Items are sorted by
    the key ascending. The reference date is ``inputs.reference_date``.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import statistics
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from control_plane.task_decomposer import get_decomposer, output_name, project_plan


CLAIM_BOUNDARY: dict[str, Any] = {
    "l2_granted": False,
    "l2_accepted": False,
    "l2_status": "CONDITIONAL",
    "production_7x24": "NOT ACCEPTED",
    "l2_2_72h_clock": "NOT STARTED",
    "observation_card": False,
    "t3_run": False,
    "t1_or_t2_rerun": False,
}

# Write-protection only. These ids are refused so this runner cannot rerun
# the historical observation inboxes. They are not a job-selection table.
HISTORICAL_OBSERVATION_TASK_IDS = frozenset({
    "DS-T1-20261108",
    "DS-T2-20261110",
})

NUMERIC_SHARE = Decimal("0.8")
OUTLIER_MIN_N = 4
OUTLIER_MAD_MULTIPLIER = 3

_DECOMPOSER_KEYS = (
    "statement",
    "text",
    "title",
    "description",
    "goal",
    "schema",
    "columns",
    "reference_date",
)


def run_card(card_dir: Path, out_dir: Path) -> dict[str, Any]:
    """Load ``goal.json`` plus its input file and derive-then-execute.

    ``dispatch.json`` and ``worker_jobs.py`` in the card directory are not
    opened. A protected historical inbox is refused before any read.
    """
    card_dir = Path(card_dir)
    out_dir = Path(out_dir)
    if _is_protected(card_dir, out_dir):
        return _refused()
    goal_path = card_dir / "goal.json"
    if not goal_path.is_file():
        return _error("missing_goal")
    try:
        loaded = json.loads(goal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _error("invalid_goal", detail=type(exc).__name__)
    if not isinstance(loaded, dict):
        return _error("invalid_goal", detail="goal.json must be an object")
    raw_input = loaded.get("input")
    if not isinstance(raw_input, str) or not raw_input.strip():
        return _error("missing_input_path", detail="goal.json input must be a path")
    csv_path = Path(raw_input)
    if not csv_path.is_absolute():
        csv_path = card_dir / csv_path
    if not _is_inside(csv_path, card_dir):
        return _error("input_escapes_card")
    return run_goal(loaded, csv_path, out_dir)


def run_goal(goal: dict[str, Any], csv_path: Path, out_dir: Path) -> dict[str, Any]:
    """Derive jobs from ``goal``, execute them on ``csv_path``, write ``out_dir``."""
    if _is_protected(csv_path, out_dir):
        return _refused()
    if not isinstance(goal, dict):
        raise TypeError("goal must be a dict")
    started = _utc()
    try:
        jobs = copy.deepcopy(get_decomposer().decompose(goal))
    except TypeError as exc:
        return _error("invalid_goal", detail=str(exc))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = Path(csv_path)
    steps: list[dict[str, Any]] = [{
        "step": "decompose",
        "job_count": len(jobs),
        "kinds": [job.get("kind") for job in jobs],
    }]
    if not jobs:
        _write_dispatch(out_dir, goal, csv_path, jobs, evidence_name=None)
        steps.append({"step": "write_derived_dispatch"})
        _write_worklog(out_dir, started, steps, ok=False, error="no_jobs_derived")
        _maybe_write_plan_envelope(out_dir, goal, csv_path, jobs)
        return _result(False, "no_jobs_derived", out_dir, jobs)

    if not csv_path.is_file():
        for job in jobs:
            _mark(job, "FAILED", error="missing_input")
        _write_dispatch(out_dir, goal, csv_path, jobs, evidence_name=None)
        steps.append({"step": "write_derived_dispatch"})
        _write_worklog(out_dir, started, steps, ok=False, error="missing_input")
        _maybe_write_plan_envelope(out_dir, goal, csv_path, jobs)
        return _result(False, "missing_input", out_dir, jobs)

    try:
        header, rows = _load_table(csv_path)
    except UnicodeError:
        for job in jobs:
            _mark(job, "FAILED", error="invalid_input_encoding")
        _write_dispatch(out_dir, goal, csv_path, jobs, evidence_name=None)
        steps.append({"step": "write_derived_dispatch"})
        _write_worklog(out_dir, started, steps, ok=False, error="invalid_input_encoding")
        _maybe_write_plan_envelope(out_dir, goal, csv_path, jobs)
        return _result(False, "invalid_input_encoding", out_dir, jobs)
    except csv.Error as exc:
        for job in jobs:
            _mark(job, "FAILED", error=f"invalid_csv:{exc}")
        _write_dispatch(out_dir, goal, csv_path, jobs, evidence_name=None)
        steps.append({"step": "write_derived_dispatch"})
        _write_worklog(out_dir, started, steps, ok=False, error="invalid_csv")
        _maybe_write_plan_envelope(out_dir, goal, csv_path, jobs)
        return _result(False, "invalid_csv", out_dir, jobs)

    evidence_name = _execute(jobs, header, rows, csv_path, out_dir, steps)
    _write_dispatch(out_dir, goal, csv_path, jobs, evidence_name=evidence_name)
    steps.append({"step": "write_derived_dispatch"})
    ok = all(job.get("status") == "DONE" for job in jobs)
    error = None if ok else "job_failed"
    _write_worklog(out_dir, started, steps, ok=ok, error=error)
    _maybe_write_plan_envelope(out_dir, goal, csv_path, jobs)
    return _result(ok, error, out_dir, jobs)


def execute_jobs(jobs: list[dict[str, Any]], csv_path: Path, out_dir: Path) -> dict[str, Any]:
    """Execute ``jobs`` as given. Used by tests that pass structured inputs.

    The product entry points are ``run_goal`` and ``run_card``. They call
    ``decompose`` first. This function does not read a dispatch file and
    does not import a worker module.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    header, rows = _load_table(csv_path)
    steps: list[dict[str, Any]] = []
    _execute(jobs, header, rows, Path(csv_path), out_dir, steps)
    ok = bool(jobs) and all(job.get("status") == "DONE" for job in jobs)
    return {"ok": ok, "jobs": jobs, "steps": steps}


def _execute(
    jobs: list[dict[str, Any]],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    out_dir: Path,
    steps: list[dict[str, Any]],
) -> Optional[str]:
    key = _key_column(jobs)
    blocked = False
    written: dict[str, Path] = {}
    evidence_job: Optional[dict[str, Any]] = None
    for job in jobs:
        kind = job.get("kind")
        if kind == "evidence_pack":
            evidence_job = job
            continue
        if blocked:
            _mark(job, "SKIPPED", error="skipped_after_verify_failure")
            steps.append(_step(job))
            continue
        payload, status, error = _run_one(job, header, rows, csv_path, key)
        if payload is None:
            _mark(job, status, error=error)
            steps.append(_step(job))
            if kind == "verify_input_schema" and status != "DONE":
                blocked = True
            continue
        name = output_name(job)
        _write_json(out_dir / name, payload)
        written[name] = out_dir / name
        _mark(job, status, output=name, error=error)
        steps.append(_step(job))
        if kind == "verify_input_schema" and status != "DONE":
            blocked = True

    if evidence_job is None:
        return None
    name = output_name(evidence_job)
    payload = _evidence_payload(evidence_job, jobs, csv_path, written, name)
    _write_json(out_dir / name, payload)
    _mark(evidence_job, "DONE", output=name, error=None)
    steps.append(_step(evidence_job))
    return name


def _run_one(
    job: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    kind = job.get("kind")
    inputs = job.get("inputs")
    if not isinstance(inputs, dict):
        return None, "FAILED", "invalid_inputs"
    handler = _HANDLERS.get(kind)
    if handler is None:
        return None, "FAILED", f"unsupported_kind:{kind}"
    return handler(job, inputs, header, rows, csv_path, key)


def _verify(
    job: dict[str, Any],
    inputs: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    del key
    columns = inputs.get("columns")
    declared_key = inputs.get("key")
    if not isinstance(columns, list) or not all(isinstance(name, str) for name in columns):
        return None, "FAILED", "invalid_inputs"
    problems: list[str] = []
    if header != columns:
        problems.append("header_mismatch")
    duplicate_keys: list[str] = []
    blank_keys = 0
    if declared_key is not None:
        if not isinstance(declared_key, str) or declared_key not in columns:
            problems.append("missing_key_column")
        elif header == columns:
            seen: dict[str, int] = {}
            for row in rows:
                value = row.get(declared_key, "")
                if value == "":
                    blank_keys += 1
                    continue
                seen[value] = seen.get(value, 0) + 1
            duplicate_keys = sorted(value for value, count in seen.items() if count > 1)
            if blank_keys:
                problems.append("blank_key")
            if duplicate_keys:
                problems.append("duplicate_key")
    meta = _file_meta(csv_path)
    payload = {
        "kind": "verify_input_schema",
        "job_id": job.get("job_id"),
        "key": declared_key,
        "columns": columns,
        "header": header,
        "header_match": header == columns,
        "rows": len(rows),
        "blank_keys": blank_keys,
        "duplicate_keys": duplicate_keys,
        "sha256": meta["sha256"],
        "bytes": meta["bytes"],
        "problems": problems,
    }
    if problems:
        return payload, "FAILED", ",".join(problems)
    return payload, "DONE", None


def _aggregate(
    job: dict[str, Any],
    inputs: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    del csv_path, key
    grain = inputs.get("grain")
    measures = inputs.get("measures")
    time_column = inputs.get("time_column")
    group_by = inputs.get("group_by")
    if grain not in {"month", "week"}:
        return None, "FAILED", "invalid_grain"
    if not isinstance(measures, list) or not measures or not all(isinstance(m, str) for m in measures):
        return None, "FAILED", "invalid_inputs"
    if not isinstance(time_column, str):
        return None, "FAILED", "invalid_inputs"
    if group_by is not None and not isinstance(group_by, str):
        return None, "FAILED", "invalid_inputs"
    needed = [time_column, *measures, *([group_by] if group_by else [])]
    missing = [name for name in needed if name not in header]
    if missing:
        return None, "FAILED", "missing_column:" + ",".join(missing)

    buckets: dict[tuple[str, Optional[str]], dict[str, Any]] = {}
    skipped = 0
    for row in rows:
        stamp = _parse_ts(row.get(time_column, ""))
        if stamp is None:
            skipped += 1
            continue
        period = _period(stamp, grain)
        group = row.get(group_by, "") if group_by else None
        slot = buckets.get((period, group))
        if slot is None:
            slot = {
                "period": period,
                "group": group,
                "rows": 0,
                "sums": {measure: Decimal("0") for measure in measures},
                "unparsed": {measure: 0 for measure in measures},
            }
            buckets[(period, group)] = slot
        slot["rows"] += 1
        for measure in measures:
            parsed = _parse_decimal(row.get(measure, ""))
            if parsed is None:
                slot["unparsed"][measure] += 1
            else:
                slot["sums"][measure] += parsed

    ordered = sorted(buckets.values(), key=lambda item: (item["period"], item["group"] or ""))
    payload_buckets = []
    for item in ordered:
        payload_buckets.append({
            "period": item["period"],
            "group": item["group"],
            "rows": item["rows"],
            "sums": {name: _dec_text(total) for name, total in item["sums"].items()},
            "unparsed": dict(item["unparsed"]),
        })
    payload = {
        "kind": "temporal_aggregate",
        "job_id": job.get("job_id"),
        "grain": grain,
        "measures": list(measures),
        "time_column": time_column,
        "group_by": group_by,
        "skipped_rows": skipped,
        "buckets": payload_buckets,
    }
    return payload, "DONE", None


def _anomalies(
    job: dict[str, Any],
    inputs: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    del csv_path
    columns = inputs.get("columns")
    if not isinstance(columns, list) or not all(isinstance(name, str) for name in columns):
        return None, "FAILED", "invalid_inputs"
    missing = [name for name in columns if name not in header]
    if missing:
        return None, "FAILED", "missing_column:" + ",".join(missing)

    anomalies: list[dict[str, Any]] = []
    column_stats: dict[str, Any] = {}
    for column in columns:
        numeric, parsed, nonblank = _numeric_profile(rows, column)
        outlier_rows: set[int] = set()
        stats: dict[str, Any] = {
            "numeric": numeric,
            "nonblank": nonblank,
            "parsed": len(parsed),
            "median": None,
            "mad": None,
            "threshold": None,
            "high_outlier_applied": False,
        }
        if numeric and len(parsed) >= OUTLIER_MIN_N:
            values = [item[1] for item in parsed]
            mid = statistics.median(values)
            mad = statistics.median([abs(value - mid) for value in values])
            stats["median"] = _dec_text(mid)
            stats["mad"] = _dec_text(mad)
            if mad > 0:
                threshold = mid + (Decimal(OUTLIER_MAD_MULTIPLIER) * mad)
                stats["threshold"] = _dec_text(threshold)
                stats["high_outlier_applied"] = True
                outlier_rows = {index for index, value, _raw in parsed if value > threshold}
        column_stats[column] = stats

        for index, row in enumerate(rows, start=1):
            raw = row.get(column, "")
            row_key = _row_key(row, key, index)
            if raw == "":
                anomalies.append({
                    "key": row_key, "column": column, "type": "missing", "value": raw,
                })
                continue
            if not numeric:
                continue
            parsed_value = _parse_decimal(raw)
            if parsed_value is None:
                anomalies.append({
                    "key": row_key, "column": column, "type": "non_numeric", "value": raw,
                })
                continue
            if parsed_value < 0:
                anomalies.append({
                    "key": row_key, "column": column, "type": "negative", "value": raw,
                })
            if index in outlier_rows:
                anomalies.append({
                    "key": row_key, "column": column, "type": "high_outlier", "value": raw,
                })

    anomalies.sort(key=lambda item: (item["key"], item["column"], item["type"]))
    payload = {
        "kind": "anomaly_list",
        "job_id": job.get("job_id"),
        "columns": list(columns),
        "numeric_share_threshold": _dec_text(NUMERIC_SHARE),
        "outlier_min_n": OUTLIER_MIN_N,
        "outlier_rule": "median + 3 * MAD",
        "column_stats": column_stats,
        "anomalies": anomalies,
    }
    return payload, "DONE", None


def _sla(
    job: dict[str, Any],
    inputs: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    del csv_path
    group_by = inputs.get("group_by")
    start = inputs.get("start")
    end = inputs.get("end")
    if not isinstance(group_by, str) or not isinstance(start, str) or not isinstance(end, str):
        return None, "FAILED", "invalid_inputs"
    missing = [name for name in (group_by, start, end) if name not in header]
    if missing:
        return None, "FAILED", "missing_column:" + ",".join(missing)

    breaches: list[dict[str, Any]] = []
    groups: dict[str, int] = {}
    for index, row in enumerate(rows, start=1):
        group = row.get(group_by, "")
        groups.setdefault(group, 0)
        start_raw = row.get(start, "")
        end_raw = row.get(end, "")
        start_ts = _parse_ts(start_raw)
        breach_type: Optional[str] = None
        if start_raw == "" or start_ts is None:
            breach_type = "missing_or_bad_start"
        elif end_raw == "":
            breach_type = "missing_end"
        else:
            end_ts = _parse_ts(end_raw)
            if end_ts is None:
                breach_type = "bad_end"
            elif end_ts < start_ts:
                breach_type = "end_before_start"
        if breach_type is None:
            continue
        groups[group] += 1
        breaches.append({
            "key": _row_key(row, key, index),
            "group": group,
            "type": breach_type,
            "start": start_raw,
            "end": end_raw,
        })
    breaches.sort(key=lambda item: (item["key"], item["type"]))
    payload = {
        "kind": "sla_breach_list",
        "job_id": job.get("job_id"),
        "group_by": group_by,
        "start": start,
        "end": end,
        "threshold": None,
        "rule": [
            "missing_or_bad_start",
            "missing_end",
            "bad_end",
            "end_before_start",
        ],
        "breaches": breaches,
        "by_group": {name: groups[name] for name in sorted(groups)},
    }
    return payload, "DONE", None


def _aging(
    job: dict[str, Any],
    inputs: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    del csv_path
    grain = inputs.get("grain")
    open_name = inputs.get("open")
    close_name = inputs.get("close")
    if grain not in {"month", "week", None}:
        return None, "FAILED", "invalid_grain"
    if not isinstance(open_name, str):
        return None, "FAILED", "invalid_inputs"
    if close_name is not None and not isinstance(close_name, str):
        return None, "FAILED", "invalid_inputs"
    needed = [open_name] if close_name is None else [open_name, close_name]
    missing = [name for name in needed if name not in header]
    if missing:
        return None, "FAILED", "missing_column:" + ",".join(missing)

    parsed_times: list[datetime] = []
    prepared: list[tuple[int, dict[str, str], Optional[datetime], Optional[datetime], str]] = []
    for index, row in enumerate(rows, start=1):
        opened = _parse_ts(row.get(open_name, ""))
        if close_name is None:
            closed = None
            close_state = "blank"
        else:
            closed = _parse_ts(row.get(close_name, ""))
            close_raw = row.get(close_name, "")
            close_state = "blank" if close_raw == "" else ("ok" if closed is not None else "bad")
        if opened is not None:
            parsed_times.append(opened)
        if closed is not None:
            parsed_times.append(closed)
        prepared.append((index, row, opened, closed, close_state))
    if not parsed_times:
        return None, "FAILED", "no_timestamps"
    as_of = max(parsed_times)

    skipped_open = 0
    inconsistent: list[dict[str, Any]] = []
    backlog: list[dict[str, Any]] = []
    buckets: dict[str, dict[str, int]] = {}

    for index, row, opened, closed, close_state in prepared:
        row_key = _row_key(row, key, index)
        if opened is None:
            skipped_open += 1
            continue
        period = _period(opened, grain) if grain else "all"
        if close_state == "bad" or (closed is not None and closed < opened):
            inconsistent.append({
                "key": row_key,
                "type": "bad_close" if close_state == "bad" else "close_before_open",
                "period": period,
            })
            continue
        slot = buckets.setdefault(period, {
            "opened": 0,
            "still_open": 0,
            "closed": 0,
            "open_age_seconds_sum": 0,
            "closed_age_seconds_sum": 0,
        })
        slot["opened"] += 1
        if closed is None:
            age = int((as_of - opened).total_seconds())
            slot["still_open"] += 1
            slot["open_age_seconds_sum"] += age
            backlog.append({
                "key": row_key,
                "period": period,
                "open": _canonical_ts(opened),
                "age_seconds": age,
            })
        else:
            age = int((closed - opened).total_seconds())
            slot["closed"] += 1
            slot["closed_age_seconds_sum"] += age

    inconsistent.sort(key=lambda item: item["key"])
    backlog.sort(key=lambda item: item["key"])
    payload_buckets = [
        {"period": period, **buckets[period]}
        for period in sorted(buckets)
    ]
    payload = {
        "kind": "backlog_aging",
        "job_id": job.get("job_id"),
        "grain": grain,
        "open": open_name,
        "close": close_name,
        "as_of": _canonical_ts(as_of),
        "as_of_rule": "max parsed timestamp among the open and close columns",
        "skipped_open": skipped_open,
        "inconsistent": inconsistent,
        "backlog": backlog,
        "buckets": payload_buckets,
    }
    return payload, "DONE", None


def _evidence_payload(
    job: dict[str, Any],
    jobs: list[dict[str, Any]],
    csv_path: Path,
    written: dict[str, Path],
    evidence_name: str,
) -> dict[str, Any]:
    inputs = job.get("inputs") if isinstance(job.get("inputs"), dict) else {}
    covered = []
    for other in jobs:
        if other is job:
            continue
        covered.append({
            "job_id": other.get("job_id"),
            "kind": other.get("kind"),
            "status": other.get("status"),
            "output": other.get("output"),
        })
    return {
        "kind": "evidence_pack",
        "job_id": job.get("job_id"),
        "roles": list(inputs.get("roles") or []),
        "covers": list(inputs.get("covers") or []),
        "covered_jobs": covered,
        "input": {"name": csv_path.name, **_file_meta(csv_path)},
        "outputs": {name: _file_meta(path) for name, path in sorted(written.items())},
        "excludes": ["derived_dispatch.json", "worklog.json", evidence_name],
        "network": False,
        "paid": False,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def _loan_summary(
    job: dict[str, Any],
    inputs: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    del csv_path, key
    needed_keys = (
        "key", "member", "time_column", "category", "start", "end", "duration", "reference_date",
    )
    del job
    if any(not isinstance(inputs.get(name), str) or not inputs.get(name) for name in needed_keys):
        return None, "FAILED", "invalid_inputs"
    top_n = inputs.get("top_n")
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        return None, "FAILED", "invalid_inputs"
    if inputs.get("tie_break") != "count_desc_then_id_asc":
        return None, "FAILED", "invalid_inputs"
    try:
        reference = date.fromisoformat(inputs["reference_date"])
    except ValueError:
        return None, "FAILED", "invalid_reference_date"
    columns = [inputs[name] for name in ("member", "time_column", "category", "start", "end", "duration")]
    missing = [name for name in columns if name not in header]
    if missing:
        return None, "FAILED", "missing_column:" + ",".join(missing)

    total = 0
    returned = 0
    overdue = 0
    by_category: dict[str, int] = {}
    by_month: dict[str, int] = {}
    members: dict[str, int] = {}
    for row in rows:
        total += 1
        if row.get(inputs["end"], "").strip():
            returned += 1
        elif _row_is_overdue(row, inputs["start"], inputs["duration"], reference):
            overdue += 1
        category = row.get(inputs["category"], "")
        by_category[category] = by_category.get(category, 0) + 1
        borrowed = _parse_date(row.get(inputs["time_column"], ""))
        if borrowed is not None:
            month = f"{borrowed.year:04d}-{borrowed.month:02d}"
            by_month[month] = by_month.get(month, 0) + 1
        member = row.get(inputs["member"], "")
        members[member] = members.get(member, 0) + 1
    ranked = sorted(members.items(), key=lambda item: (-item[1], item[0]))[:top_n]
    member_field = inputs["member"]
    payload = {
        "total_loans": total,
        "total_returned": returned,
        "total_outstanding": total - returned,
        "total_overdue": overdue,
        "by_category": {name: by_category[name] for name in sorted(by_category)},
        "by_month": {name: by_month[name] for name in sorted(by_month)},
        "top10_members": [
            {member_field: member_id, "loans": count}
            for member_id, count in ranked
        ],
    }
    return payload, "DONE", None


def _overdue(
    job: dict[str, Any],
    inputs: dict[str, Any],
    header: list[str],
    rows: list[dict[str, str]],
    csv_path: Path,
    key: Optional[str],
) -> tuple[Optional[dict[str, Any]], str, Optional[str]]:
    del job, csv_path, key
    for name in ("key", "start", "duration", "end", "reference_date"):
        if not isinstance(inputs.get(name), str) or not inputs.get(name):
            return None, "FAILED", "invalid_inputs"
    try:
        reference = date.fromisoformat(inputs["reference_date"])
    except ValueError:
        return None, "FAILED", "invalid_reference_date"
    missing = [
        name for name in (inputs["key"], inputs["start"], inputs["duration"], inputs["end"])
        if name not in header
    ]
    if missing:
        return None, "FAILED", "missing_column:" + ",".join(missing)
    key_name = inputs["key"]
    values = []
    for row in rows:
        if row.get(inputs["end"], "").strip():
            continue
        if not _row_is_overdue(row, inputs["start"], inputs["duration"], reference):
            continue
        values.append(_json_key(row.get(key_name, "")))
    values.sort(key=_sort_key)
    return {"items": [{key_name: value} for value in values]}, "DONE", None


def _row_is_overdue(row: dict[str, str], start: str, duration: str, reference: date) -> bool:
    borrowed = _parse_date(row.get(start, ""))
    days = _parse_decimal(row.get(duration, ""))
    if borrowed is None or days is None:
        return False
    return Decimal((reference - borrowed).days) > days


def _parse_date(value: str) -> Optional[date]:
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _json_key(raw: str) -> Any:
    text = raw.strip()
    if text.isdigit():
        return int(text)
    return text


def _sort_key(value: Any) -> tuple:
    if isinstance(value, int) and not isinstance(value, bool):
        return (0, value)
    return (1, str(value))


_HANDLERS = {
    "verify_input_schema": _verify,
    "temporal_aggregate": _aggregate,
    "anomaly_list": _anomalies,
    "sla_breach_list": _sla,
    "backlog_aging": _aging,
    "loan_operations_summary": _loan_summary,
    "overdue_list": _overdue,
}


def _write_dispatch(
    out_dir: Path,
    goal: dict[str, Any],
    csv_path: Path,
    jobs: list[dict[str, Any]],
    evidence_name: Optional[str],
) -> None:
    evidence = None
    if evidence_name:
        evidence = {"name": evidence_name, **_file_meta(out_dir / evidence_name)}
    input_meta = None
    if csv_path.is_file():
        try:
            input_meta = {"name": csv_path.name, **_file_meta(csv_path)}
        except OSError:
            input_meta = {"name": csv_path.name}
    payload = {
        "produced_by": "control_plane.task_decomposer.TaskDecomposer.decompose",
        "written_after_derivation": True,
        "read_as_job_source": False,
        "used_worker_jobs_py": False,
        "decomposer_fields": {
            key: goal[key] for key in _DECOMPOSER_KEYS if key in goal
        },
        "ignored_keys": sorted(
            key for key in goal if key not in _DECOMPOSER_KEYS and key != "input"
        ),
        "input": input_meta,
        "jobs": jobs,
        "evidence_pack": evidence,
        "ok": bool(jobs) and all(job.get("status") == "DONE" for job in jobs),
        "network": False,
        "paid": False,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    _write_json(out_dir / "derived_dispatch.json", payload)


def _write_worklog(
    out_dir: Path,
    started: str,
    steps: list[dict[str, Any]],
    *,
    ok: bool,
    error: Optional[str],
) -> None:
    payload = {
        "worker": "scripts/worker_run_task.py",
        "path": "derive_then_execute",
        "started_utc": started,
        "finished_utc": _utc(),
        "decomposer": "control_plane.task_decomposer.TaskDecomposer.decompose",
        "used_preauthored_dispatch": False,
        "used_worker_jobs_py": False,
        "ok": ok,
        "error": error,
        "steps": steps,
        "network": False,
        "paid": False,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    _write_json(out_dir / "worklog.json", payload)


def _maybe_write_plan_envelope(
    out_dir: Path,
    goal: dict[str, Any],
    csv_path: Path,
    jobs: list[dict[str, Any]],
) -> None:
    """Write plan.json, report.md, and manifest.json for a loan-shaped run.

    The trigger is the derived job kinds, not a task id. ``plan.json`` is a
    projection of the jobs ``decompose`` already returned. The manifest
    copies ``task_id`` onto the record when the goal carries one. It does
    not use that id to choose jobs. ``worklog.json`` is left out of the
    manifest because its clock changes between runs.
    """
    kinds = {job.get("kind") for job in jobs}
    if not ({"loan_operations_summary", "overdue_list"} & kinds):
        return
    plan = project_plan(goal, jobs, Path(csv_path).name)
    for task, job in zip(plan["derived_tasks"], jobs):
        if job.get("kind") == "evidence_pack" and job.get("status") == "DONE":
            task["outputs"] = list(task["outputs"]) + ["report.md", "manifest.json"]
    _write_json(out_dir / "plan.json", plan)
    report = _render_report(goal, jobs, plan, csv_path, out_dir)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    files: dict[str, Any] = {}
    for path in sorted(out_dir.iterdir()):
        if not path.is_file() or path.name in {"manifest.json", "worklog.json"}:
            continue
        files[path.name] = _file_meta(path)
    task_id = goal.get("task_id") if isinstance(goal.get("task_id"), str) else None
    input_meta: dict[str, Any] = {"name": Path(csv_path).name}
    if csv_path.is_file():
        try:
            input_meta.update(_file_meta(csv_path))
            text = csv_path.read_text(encoding="utf-8")
            input_meta["lines"] = len(text.splitlines())
        except (OSError, UnicodeError):
            input_meta["unreadable"] = True
    payload = {
        "task_id": task_id,
        "goal": plan["goal"],
        "input": input_meta,
        "deliverables": files,
        "derivation": {
            "produced_by": "control_plane.task_decomposer.TaskDecomposer.decompose",
            "plan_projected_from_decompose": True,
            "read_as_job_source": False,
            "used_preauthored_dispatch": False,
            "used_worker_jobs_py": False,
        },
        "submission": {
            "submitted_for_observation": goal.get("observation_card") is True,
            "observation_track_acceptance": False,
            "l2_granted": False,
            "l2_accepted": False,
            "l2_status": "CONDITIONAL",
            "production_7x24": "NOT ACCEPTED",
            "l2_2_72h_clock": "NOT STARTED",
            "comment_6761044915_is_not_a_start": True,
        },
        "network": False,
        "paid": False,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    _write_json(out_dir / "manifest.json", payload)


def _render_report(
    goal: dict[str, Any],
    jobs: list[dict[str, Any]],
    plan: dict[str, Any],
    csv_path: Path,
    out_dir: Path,
) -> str:
    task_id = goal.get("task_id") if isinstance(goal.get("task_id"), str) else "(none)"
    if goal.get("observation_card") is True:
        opening = (
            f"`{task_id}` is submitted for observation-track acceptance. "
            "This is a T3 run submitted for observation-track acceptance. "
            "Observation-track acceptance is not claimed. "
            "claim_boundary.t3_run stays false on every run, including this one. "
            "That constant does not grant or accept the submission."
        )
    else:
        opening = (
            "This run is not an observation card. "
            "Observation-track acceptance is not claimed."
        )
    summary_path = out_dir / "summary.json"
    overdue_path = out_dir / "overdue.json"
    summary = _read_json_if_present(summary_path)
    overdue = _read_json_if_present(overdue_path)
    input_line = "Input file was not readable."
    if csv_path.is_file():
        try:
            meta = _file_meta(csv_path)
            line_count = len(csv_path.read_text(encoding="utf-8").splitlines())
            input_line = (
                f"Input `{csv_path.name}` sha256 `{meta['sha256']}`, "
                f"{meta['bytes']} bytes, {line_count} lines."
            )
        except (OSError, UnicodeError):
            input_line = f"Input `{csv_path.name}` could not be read."
    lines = [
        f"# {task_id}",
        "",
        opening,
        "",
        "L2 is not granted and not accepted.",
        "",
        "Production 7×24 is NOT ACCEPTED.",
        "",
        "The L2-2 72h clock is NOT STARTED. Comment 6761044915 is not a start.",
        "",
        "## Goal",
        "",
        str(plan.get("goal") or ""),
        "",
        "## Why this split",
        "",
        str(plan.get("why") or ""),
        "",
        "## Alternatives considered",
        "",
    ]
    for item in plan.get("alternatives_considered") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Derived tasks", ""])
    for task in plan.get("derived_tasks") or []:
        lines.append(
            f"- `{task.get('task_id')}` {task.get('purpose')} "
            f"outputs: {', '.join(task.get('outputs') or []) or '(none)'}."
        )
    lines.extend([
        "",
        "## Rules used for the numbers",
        "",
        "A loan is returned when the return-date cell is non-blank. Outstanding means that cell is blank. A populated return date is not reinterpreted against the reference date.",
        "",
        "Overdue means outstanding and (reference date − borrowed date) in whole days is greater than loan days. Equal to the loan days is not overdue. The reference date is the `reference_date` on the derived job, not a date built into the executor.",
        "",
        "Category counts and month counts include every loan. The month is the borrow date's `YYYY-MM`. The top members are ranked by loan count descending, then member id ascending.",
        "",
        "## Results",
        "",
    ])
    if isinstance(summary, dict):
        lines.append(f"- total_loans: {summary.get('total_loans')}")
        lines.append(f"- total_returned: {summary.get('total_returned')}")
        lines.append(f"- total_outstanding: {summary.get('total_outstanding')}")
        lines.append(f"- total_overdue: {summary.get('total_overdue')}")
        lines.append(f"- by_category: {json.dumps(summary.get('by_category'), ensure_ascii=False)}")
        lines.append(f"- by_month: {json.dumps(summary.get('by_month'), ensure_ascii=False)}")
        lines.append(f"- top10_members: {json.dumps(summary.get('top10_members'), ensure_ascii=False)}")
    else:
        lines.append("summary.json was not written.")
    if isinstance(overdue, dict) and isinstance(overdue.get("items"), list):
        lines.append(f"- overdue items: {len(overdue['items'])}")
    else:
        lines.append("overdue.json was not written.")
    lines.extend([
        "",
        "## Input",
        "",
        input_line,
        "",
        "## Derivation",
        "",
        "Jobs were produced by `TaskDecomposer.decompose()`. `plan.json` is a projection of those jobs. `derived_dispatch.json` was written after derivation and was not read as an input. No pre-written `dispatch.json` was read. `worker_jobs.py` was not imported.",
        "",
    ])
    return "\n".join(lines)


def _read_json_if_present(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _key_column(jobs: list[dict[str, Any]]) -> Optional[str]:
    for job in jobs:
        if job.get("kind") != "verify_input_schema":
            continue
        inputs = job.get("inputs")
        if isinstance(inputs, dict) and isinstance(inputs.get("key"), str):
            return inputs["key"]
    return None


def _numeric_profile(
    rows: list[dict[str, str]],
    column: str,
) -> tuple[bool, list[tuple[int, Decimal, str]], int]:
    parsed: list[tuple[int, Decimal, str]] = []
    nonblank = 0
    for index, row in enumerate(rows, start=1):
        raw = row.get(column, "")
        if raw == "":
            continue
        nonblank += 1
        value = _parse_decimal(raw)
        if value is not None:
            parsed.append((index, value, raw))
    if nonblank == 0:
        return False, [], 0
    share = Decimal(len(parsed)) / Decimal(nonblank)
    if share >= NUMERIC_SHARE:
        return True, parsed, nonblank
    return False, [], nonblank


def _load_table(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = csv_path.read_text(encoding="utf-8")
    reader = csv.reader(io.StringIO(text))
    raw_rows = list(reader)
    if not raw_rows:
        return [], []
    header = [cell.strip() for cell in raw_rows[0]]
    rows: list[dict[str, str]] = []
    width = len(header)
    for raw in raw_rows[1:]:
        if not any(cell.strip() for cell in raw):
            continue
        padded = list(raw) + [""] * (width - len(raw))
        rows.append({
            header[index]: padded[index].strip() if index < len(padded) else ""
            for index in range(width)
        })
    return header, rows


def _parse_ts(value: str) -> Optional[datetime]:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _canonical_ts(value: datetime) -> str:
    if value.microsecond:
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _period(value: datetime, grain: str) -> str:
    if grain == "month":
        return f"{value.year:04d}-{value.month:02d}"
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _parse_decimal(value: str) -> Optional[Decimal]:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _dec_text(value: Decimal) -> str:
    return format(value, "f")


def _row_key(row: dict[str, str], key: Optional[str], index: int) -> str:
    if key and row.get(key, "") != "":
        return row[key]
    return f"row:{index}"


def _file_meta(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _mark(
    job: dict[str, Any],
    status: str,
    *,
    output: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    job["status"] = status
    job["output"] = output
    job["error"] = error


def _step(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "step": "execute",
        "job_id": job.get("job_id"),
        "kind": job.get("kind"),
        "status": job.get("status"),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_protected(*paths: Path) -> bool:
    for path in paths:
        resolved = Path(path).resolve()
        candidates = [resolved, *resolved.parents]
        for candidate in candidates:
            if (
                candidate.name in HISTORICAL_OBSERVATION_TASK_IDS
                and candidate.parent.name == "task_inbox"
            ):
                return True
    return False


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _refused() -> dict[str, Any]:
    return _error("refusing_historical_observation_task")


def _error(code: str, detail: Optional[str] = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error": code,
        "jobs": [],
        "used_preauthored_dispatch": False,
        "used_worker_jobs_py": False,
        "network": False,
        "paid": False,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    if detail is not None:
        payload["detail"] = detail
    return payload


def _result(
    ok: bool,
    error: Optional[str],
    out_dir: Path,
    jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "ok": ok,
        "error": error,
        "out": str(out_dir),
        "jobs": [
            {
                "job_id": job.get("job_id"),
                "title": job.get("title"),
                "kind": job.get("kind"),
                "status": job.get("status"),
            }
            for job in jobs
        ],
        "used_preauthored_dispatch": False,
        "used_worker_jobs_py": False,
        "network": False,
        "paid": False,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
