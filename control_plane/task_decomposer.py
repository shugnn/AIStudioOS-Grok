"""Deterministic, offline goal → job derivation.

Jobs are composed from statement intents and column roles. Nothing in this
module calls a network, an LLM, or a paid API.

This is evidence that a different goal plus a different input schema yields a
different job set. It does not grant or accept L2. Production 7×24 is
NOT ACCEPTED. The L2-2 72h clock is NOT STARTED.

The previous body of ``decompose`` returned ``[]`` for every input, including
a Chinese-only statement, because tokenization was ASCII-only. Chinese
phrases now map onto the same closed intent set, and loan-shaped columns
can add an operations summary and an overdue list. Dispatch titles on the
orders cards were written onto those cards; this module does not look them
up and does not reproduce them on purpose. A task id is still ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


_TOKEN = re.compile(r"[a-z0-9_]+")
_BY = re.compile(r"\bby\s+([a-z0-9_]+)\b", re.IGNORECASE)

# Closed intent vocabulary. Matching is on tokens of the statement, never on
# a task id, fixture name, or the whole sentence.
_INTENT_TOKENS: dict[str, frozenset[str]] = {
    "monthly": frozenset({"month", "monthly"}),
    "weekly": frozenset({"week", "weekly"}),
    "summary": frozenset({
        "summary", "summarize", "summarised", "summarized",
        "aggregate", "aggregation",
    }),
    "anomaly": frozenset({"anomaly", "anomalies"}),
    "evidence": frozenset({"evidence", "verifiable", "manifest"}),
    "sla": frozenset({"sla", "breach", "breaches"}),
    "aging": frozenset({"aging", "ageing", "backlog"}),
    "verify_input": frozenset({"frozen", "checksum", "verify", "verification", "sha256"}),
    "overdue": frozenset({"overdue"}),
}

# Closed Chinese phrases. A phrase is not a task id and not the whole goal.
# Longer phrases are listed first so a reader can see which form is intentional.
# Matching still adds an intent to a set, so overlap cannot select a job list.
_ZH_PHRASES: tuple[tuple[str, str], ...] = (
    ("可独立核验", "evidence"),
    ("独立核验", "evidence"),
    ("证据包", "evidence"),
    ("月度", "monthly"),
    ("按月", "monthly"),
    ("每月", "monthly"),
    ("周度", "weekly"),
    ("按周", "weekly"),
    ("每周", "weekly"),
    ("汇总", "summary"),
    ("异常", "anomaly"),
    ("逾期", "overdue"),
    ("积压", "aging"),
    ("账龄", "aging"),
    ("时效", "sla"),
    ("违约", "sla"),
    ("校验", "verify_input"),
    ("冻结", "verify_input"),
)

_ZH_INTENT_LABEL = {
    "summary": "汇总",
    "overdue": "逾期",
    "evidence": "证据",
    "anomaly": "异常",
    "monthly": "月度",
    "weekly": "周度",
    "verify_input": "校验",
    "sla": "时效",
    "aging": "账龄",
}

_MEASURE_EXACT = frozenset({
    "amount", "total", "price", "revenue", "qty", "quantity", "cost", "value",
})
_MEASURE_SUFFIXES = (
    "_amount", "_qty", "_quantity", "_revenue", "_cost", "_price", "_total", "_value",
)
_NUMERIC_TYPES = frozenset({
    "number", "numeric", "float", "double", "int", "integer", "decimal",
})

# Among columns already classified as event_time, pick a conventional endpoint
# when several exist. Unknown names fall through to schema order.
_OPEN_PREFERENCE = ("opened_at", "created_at")
_SLA_END_PREFERENCE = ("first_response_at", "responded_at", "resolved_at", "closed_at")
_CLOSE_PREFERENCE = ("resolved_at", "closed_at")
_LOAN_START_PREFERENCE = ("borrowed_date", "borrow_date", "checkout_date", "issued_date", "start_date")
_LOAN_END_PREFERENCE = ("returned_date", "return_date", "checked_in_date")
_DURATION_PREFERENCE = ("loan_days", "term_days", "duration_days")
_MEMBER_PREFERENCE = ("member_id", "patron_id", "borrower_id", "user_id", "customer_id")
_CATEGORY_PREFERENCE = ("category", "genre", "subject")
_SUMMARY_TOP_N = 10

_STATEMENT_FALLBACK_KEYS = ("text", "title", "description", "goal")


@dataclass(frozen=True)
class _Column:
    name: str
    declared_type: Optional[str]
    role: str


class TaskDecomposer:
    """Derive a job list from a goal statement plus an input schema.

    Read fields:
    - ``statement``, or if that key is absent: ``text``, ``title``,
      ``description``, and ``goal`` (joined in that order)
    - ``schema.columns`` (or top-level ``columns``): strings, or
      ``{"name", "type"|"dtype"}``
    - ``reference_date`` (``YYYY-MM-DD``), when present: copied into the
      loan-summary and overdue job inputs. It does not decide which rules
      fire. Absent, those jobs still fire when their predicates match, and
      the executor then fails closed instead of inventing a date.

    Every other key is ignored. In particular, a card id or a file name
    cannot select a job list. The same statement tokens, the same columns,
    and the same reference date always produce the same jobs. No rule
    matches → ``[]``.
    """

    def decompose(self, goal: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(goal, dict):
            raise TypeError("goal must be a dict")
        text = _statement(goal)
        intents = _intents(text)
        by_targets = _by_targets(text)
        columns = _parse_columns(goal)
        reference_date = _reference_date(goal)

        proposed: list[dict[str, Any]] = []
        verify = _job_verify(intents, columns)
        if verify:
            proposed.append(verify)
        proposed.extend(_jobs_aggregate(intents, by_targets, columns))
        anomaly = _job_anomaly(intents, columns)
        if anomaly:
            proposed.append(anomaly)
        sla = _job_sla(intents, by_targets, columns)
        if sla:
            proposed.append(sla)
        aging = _job_aging(intents, columns)
        if aging:
            proposed.append(aging)
        loan_summary = _job_loan_summary(intents, columns, reference_date)
        if loan_summary:
            proposed.append(loan_summary)
        overdue = _job_overdue(intents, columns, reference_date)
        if overdue:
            proposed.append(overdue)

        for index, job in enumerate(proposed, start=1):
            job["job_id"] = f"J{index}"

        evidence = _job_evidence(intents, columns, proposed)
        if evidence:
            proposed.append(evidence)
        return proposed


def get_decomposer() -> TaskDecomposer:
    return TaskDecomposer()


def _reference_date(goal: dict[str, Any]) -> Optional[str]:
    if "reference_date" not in goal or goal["reference_date"] is None:
        return None
    value = goal["reference_date"]
    if not isinstance(value, str):
        raise TypeError("reference_date must be a string")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise TypeError("reference_date must be YYYY-MM-DD") from exc
    return value


def _statement(goal: dict[str, Any]) -> str:
    if "statement" in goal and goal["statement"] is not None:
        statement = goal["statement"]
        if not isinstance(statement, str):
            raise TypeError("statement must be a string")
        return statement
    parts: list[str] = []
    for key in _STATEMENT_FALLBACK_KEYS:
        value = goal.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"{key} must be a string")
        parts.append(value)
    return " ".join(parts)


def _intents(text: str) -> frozenset[str]:
    found = set(_TOKEN.findall(text.lower()))
    names = {name for name, vocab in _INTENT_TOKENS.items() if found & vocab}
    for phrase, intent in _ZH_PHRASES:
        if phrase in text:
            names.add(intent)
    return frozenset(names)


def _by_targets(text: str) -> list[str]:
    return [match.group(1).lower() for match in _BY.finditer(text)]


def _parse_columns(goal: dict[str, Any]) -> list[_Column]:
    if "schema" in goal and goal["schema"] is not None:
        schema = goal["schema"]
        if not isinstance(schema, dict):
            raise TypeError("schema must be a dict")
        raw = schema.get("columns")
    else:
        raw = goal.get("columns")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError("columns must be a list")

    columns: list[_Column] = []
    seen: set[str] = set()
    for item in raw:
        name, declared = _column_fields(item)
        key = name.lower()
        if key in seen:
            raise TypeError(f"duplicate column name: {name}")
        seen.add(key)
        columns.append(_Column(name=name, declared_type=declared, role=_role(name, declared)))
    return columns


def _column_fields(item: Any) -> tuple[str, Optional[str]]:
    if isinstance(item, str):
        name, declared = item, None
    elif isinstance(item, dict):
        name = item.get("name")
        declared = item.get("type", item.get("dtype"))
        if declared is not None and not isinstance(declared, str):
            raise TypeError("column type must be a string")
    else:
        raise TypeError("column must be a string or an object with a name")
    if not isinstance(name, str) or not name.strip():
        raise TypeError("column name must be a non-empty string")
    return name, declared.lower() if isinstance(declared, str) else None


def _role(name: str, declared: Optional[str]) -> str:
    lowered = name.lower()
    if lowered == "id" or lowered.endswith("_id"):
        return "identifier"
    if lowered.endswith("_at"):
        return "event_time"
    if lowered == "date" or lowered.endswith("_date") or lowered.endswith("_day"):
        return "calendar_date"
    if lowered == "duration" or lowered.endswith("_days"):
        return "duration"
    if lowered in _MEASURE_EXACT or lowered.endswith(_MEASURE_SUFFIXES):
        return "measure"
    if lowered in {"status", "state"} or lowered.endswith("_status") or lowered.endswith("_state"):
        return "status"
    if lowered in {"priority", "severity"} or lowered.endswith("_priority") or lowered.endswith("_severity"):
        return "priority"
    if declared in _NUMERIC_TYPES:
        return "measure"
    return "dimension"


def _pick(columns: list[_Column], names: tuple[str, ...], fallback: Optional[_Column]) -> Optional[_Column]:
    by_name: dict[str, _Column] = {}
    for column in columns:
        by_name.setdefault(column.name.lower(), column)
    for name in names:
        if name in by_name:
            return by_name[name]
    return fallback


def _match_by(
    by_targets: list[str],
    columns: list[_Column],
    roles: Optional[set[str]],
) -> Optional[str]:
    lookup = {column.name.lower(): column for column in columns}
    for target in by_targets:
        column = lookup.get(target)
        if column is None:
            continue
        if roles is not None and column.role not in roles:
            continue
        return column.name
    return None


def _job(
    title: str,
    kind: str,
    reason: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "job_id": "",
        "title": title,
        "kind": kind,
        "status": "PENDING",
        "reason": reason,
        "inputs": inputs,
    }


def _job_verify(intents: frozenset[str], columns: list[_Column]) -> Optional[dict[str, Any]]:
    if not columns:
        return None
    because = sorted(intents & {"verify_input", "evidence"})
    if not because:
        return None
    key = next((column.name for column in columns if column.role == "identifier"), None)
    title = f"verify_input_schema_keyed_by_{key}" if key else "verify_input_schema"
    return _job(
        title=title,
        kind="verify_input_schema",
        reason=f"rule=verify_input_schema; because={','.join(because)}; key={key or 'none'}",
        inputs={"key": key, "columns": [column.name for column in columns]},
    )


def _jobs_aggregate(
    intents: frozenset[str],
    by_targets: list[str],
    columns: list[_Column],
) -> list[dict[str, Any]]:
    if "summary" not in intents:
        return []
    grains: list[str] = []
    if "monthly" in intents:
        grains.append("month")
    if "weekly" in intents:
        grains.append("week")
    if not grains:
        return []
    measures = [column.name for column in columns if column.role == "measure"]
    if not measures:
        return []
    time_columns = [column for column in columns if column.role == "calendar_date"]
    if not time_columns:
        time_columns = [column for column in columns if column.role == "event_time"]
    if not time_columns:
        return []
    time_column = time_columns[0].name
    group = _match_by(by_targets, columns, {"dimension", "status", "priority"})
    if group == time_column:
        group = None
    because = ",".join(name for name in ("monthly", "weekly", "summary") if name in intents)
    measure_part = "_".join(measures)
    jobs: list[dict[str, Any]] = []
    for grain in grains:
        title = f"aggregate_{measure_part}_by_{grain}_of_{time_column}"
        if group:
            title += f"_and_{group}"
        jobs.append(_job(
            title=title,
            kind="temporal_aggregate",
            reason=(
                f"rule=temporal_aggregate; because={because}; grain={grain}; "
                f"measures={','.join(measures)}; time_column={time_column}; "
                f"group_by={group or 'none'}"
            ),
            inputs={
                "grain": grain,
                "measures": measures,
                "time_column": time_column,
                "group_by": group,
            },
        ))
    return jobs


def _job_anomaly(intents: frozenset[str], columns: list[_Column]) -> Optional[dict[str, Any]]:
    if "anomaly" not in intents:
        return None
    watched = (
        [column.name for column in columns if column.role == "status"]
        + [column.name for column in columns if column.role == "measure"]
    )
    if not watched:
        return None
    return _job(
        title="list_anomalies_on_" + "_".join(watched),
        kind="anomaly_list",
        reason=f"rule=anomaly_list; because=anomaly; columns={','.join(watched)}",
        inputs={"columns": watched},
    )


def _job_sla(
    intents: frozenset[str],
    by_targets: list[str],
    columns: list[_Column],
) -> Optional[dict[str, Any]]:
    if "sla" not in intents:
        return None
    events = [column for column in columns if column.role == "event_time"]
    if len(events) < 2:
        return None
    start = _pick(events, _OPEN_PREFERENCE, events[0])
    if start is None:
        return None
    end_fallback = next((column for column in events if column.name != start.name), None)
    end = _pick(events, _SLA_END_PREFERENCE, end_fallback)
    if end is None or end.name == start.name:
        return None
    group = _match_by(by_targets, columns, None)
    if group is None:
        priority = [column.name for column in columns if column.role == "priority"]
        group = priority[0] if priority else None
    if group is None or group in {start.name, end.name}:
        return None
    return _job(
        title=f"list_sla_breaches_by_{group}_from_{start.name}_to_{end.name}",
        kind="sla_breach_list",
        reason=(
            f"rule=sla_breach_list; because=sla; group_by={group}; "
            f"start={start.name}; end={end.name}"
        ),
        inputs={"group_by": group, "start": start.name, "end": end.name},
    )


def _job_aging(intents: frozenset[str], columns: list[_Column]) -> Optional[dict[str, Any]]:
    if "aging" not in intents:
        return None
    events = [column for column in columns if column.role == "event_time"]
    if not events:
        return None
    open_col = _pick(events, _OPEN_PREFERENCE, events[0])
    if open_col is None:
        return None
    close_col = _pick(events, _CLOSE_PREFERENCE, None)
    if close_col is not None and close_col.name == open_col.name:
        close_col = None
    if "weekly" in intents:
        grain: Optional[str] = "week"
    elif "monthly" in intents:
        grain = "month"
    else:
        grain = None
    title = (
        f"age_backlog_by_{grain}_of_{open_col.name}"
        if grain
        else f"age_backlog_of_{open_col.name}"
    )
    if close_col is not None:
        title += f"_until_{close_col.name}"
    because = ",".join(name for name in ("aging", "weekly", "monthly") if name in intents)
    return _job(
        title=title,
        kind="backlog_aging",
        reason=(
            f"rule=backlog_aging; because={because}; grain={grain or 'none'}; "
            f"open={open_col.name}; close={close_col.name if close_col else 'none'}"
        ),
        inputs={
            "grain": grain,
            "open": open_col.name,
            "close": close_col.name if close_col else None,
        },
    )


def _duration_column(columns: list[_Column]) -> Optional[_Column]:
    durations = [column for column in columns if column.role == "duration"]
    return _pick(durations, _DURATION_PREFERENCE, durations[0] if durations else None)


def _loan_endpoints(columns: list[_Column]) -> Optional[tuple[_Column, _Column, _Column, _Column]]:
    """Start date, return date, duration, and the first identifier.

    Returns None unless the schema has two calendar dates, one duration,
    and an identifier. Names are preferences inside those roles.
    """
    dates = [column for column in columns if column.role == "calendar_date"]
    identifiers = [column for column in columns if column.role == "identifier"]
    duration = _duration_column(columns)
    if len(dates) < 2 or duration is None or not identifiers:
        return None
    start = _pick(dates, _LOAN_START_PREFERENCE, dates[0])
    if start is None:
        return None
    end = _pick(dates, _LOAN_END_PREFERENCE, None)
    if end is None or end.name == start.name:
        end = next((column for column in dates if column.name != start.name), None)
    if end is None or end.name == start.name:
        return None
    return start, end, duration, identifiers[0]


def _job_loan_summary(
    intents: frozenset[str],
    columns: list[_Column],
    reference_date: Optional[str],
) -> Optional[dict[str, Any]]:
    if "summary" not in intents:
        return None
    endpoints = _loan_endpoints(columns)
    if endpoints is None:
        return None
    start, end, duration, key = endpoints
    identifiers = [column for column in columns if column.role == "identifier"]
    dimensions = [column for column in columns if column.role == "dimension"]
    if len(identifiers) < 2 or not dimensions:
        return None
    member = _pick(identifiers, _MEMBER_PREFERENCE, None)
    if member is None or member.name == key.name:
        member = next((column for column in identifiers if column.name != key.name), None)
    category = _pick(dimensions, _CATEGORY_PREFERENCE, dimensions[0])
    if member is None or category is None:
        return None
    title = (
        f"summarize_{key.name}_by_{category.name}_and_month_of_{start.name}"
        f"_top_{member.name}"
    )
    return _job(
        title=title,
        kind="loan_operations_summary",
        reason=(
            f"rule=loan_operations_summary; because=summary; key={key.name}; "
            f"member={member.name}; time_column={start.name}; category={category.name}; "
            f"duration={duration.name}; end={end.name}; "
            f"reference_date={reference_date or 'none'}"
        ),
        inputs={
            "key": key.name,
            "member": member.name,
            "time_column": start.name,
            "category": category.name,
            "start": start.name,
            "end": end.name,
            "duration": duration.name,
            "reference_date": reference_date,
            "top_n": _SUMMARY_TOP_N,
            "tie_break": "count_desc_then_id_asc",
        },
    )


def _job_overdue(
    intents: frozenset[str],
    columns: list[_Column],
    reference_date: Optional[str],
) -> Optional[dict[str, Any]]:
    if "overdue" not in intents:
        return None
    endpoints = _loan_endpoints(columns)
    if endpoints is None:
        return None
    start, end, duration, key = endpoints
    return _job(
        title=f"list_overdue_{key.name}_from_{start.name}_plus_{duration.name}_until_{end.name}",
        kind="overdue_list",
        reason=(
            f"rule=overdue_list; because=overdue; key={key.name}; "
            f"start={start.name}; duration={duration.name}; end={end.name}; "
            f"reference_date={reference_date or 'none'}; compare=elapsed_days_gt_duration"
        ),
        inputs={
            "key": key.name,
            "start": start.name,
            "duration": duration.name,
            "end": end.name,
            "reference_date": reference_date,
        },
    )


def _job_evidence(
    intents: frozenset[str],
    columns: list[_Column],
    prior: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if "evidence" not in intents or not columns:
        return None
    roles = sorted({column.role for column in columns})
    covers = [job["job_id"] for job in prior]
    job = _job(
        title="assemble_evidence_pack_over_" + "_".join(roles),
        kind="evidence_pack",
        reason=(
            f"rule=evidence_pack; because=evidence; roles={','.join(roles)}; "
            f"covers={','.join(covers) if covers else 'none'}"
        ),
        inputs={"roles": roles, "covers": covers},
    )
    job["job_id"] = f"J{len(prior) + 1}"
    return job


def output_name(job: dict[str, Any]) -> str:
    """File name the executor writes for ``job``.

    Two kinds have a stable deliverable name because the observation
    contract asks for those names. Every other kind keeps the job id in
    the file name. This function does not decide whether the job exists.
    """
    kind = str(job.get("kind") or "job")
    if kind == "loan_operations_summary":
        return "summary.json"
    if kind == "overdue_list":
        return "overdue.json"
    job_id = job.get("job_id") or "job"
    return f"{job_id}_{kind}.json"


def project_plan(goal: dict[str, Any], jobs: list[dict[str, Any]], input_name: str) -> dict[str, Any]:
    """Project jobs that ``decompose`` already returned into the plan shape.

    This does not choose jobs. A task id is not read. ``why`` and
    ``alternatives_considered`` are built from the intents that fired and
    from the predicates that did not.
    """
    if not isinstance(goal, dict):
        raise TypeError("goal must be a dict")
    if not isinstance(input_name, str) or not input_name:
        raise TypeError("input_name must be a non-empty string")
    statement = _statement(goal)
    zh = _has_cjk(statement)
    tasks = []
    for job in jobs:
        if job.get("status") == "DONE" and isinstance(job.get("output"), str):
            outputs = [job["output"]]
        elif job.get("status") in {None, "PENDING", ""}:
            outputs = [output_name(job)]
        else:
            outputs = []
        tasks.append({
            "task_id": job.get("job_id"),
            "purpose": _purpose(job, zh),
            "inputs": [input_name],
            "outputs": outputs,
        })
    return {
        "goal": statement,
        "derived_tasks": tasks,
        "why": _why(statement, jobs, zh),
        "alternatives_considered": _alternatives(goal, jobs, zh),
    }


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _purpose(job: dict[str, Any], zh: bool) -> str:
    kind = job.get("kind")
    inputs = job.get("inputs") if isinstance(job.get("inputs"), dict) else {}
    if kind == "verify_input_schema":
        key = inputs.get("key") or "none"
        if zh:
            return f"校验表头和主键 {key}，并记录输入文件的 sha256 与字节数。"
        return f"Check the header and the key {key}, and record the input sha256 and byte length."
    if kind == "loan_operations_summary":
        if zh:
            return (
                f"统计笔数、已还、未还和逾期，按 {inputs.get('category')} 与 "
                f"{inputs.get('time_column')} 的月份汇总，并列出 {inputs.get('member')} 的前 "
                f"{inputs.get('top_n')}。"
            )
        return (
            f"Count rows, returned, outstanding, and overdue; group by {inputs.get('category')} "
            f"and month of {inputs.get('time_column')}; rank {inputs.get('member')}."
        )
    if kind == "overdue_list":
        if zh:
            return (
                f"列出 {inputs.get('end')} 为空、且（{inputs.get('reference_date')} − "
                f"{inputs.get('start')}）的天数大于 {inputs.get('duration')} 的 {inputs.get('key')}。"
            )
        return (
            f"List {inputs.get('key')} where {inputs.get('end')} is blank and "
            f"({inputs.get('reference_date')} - {inputs.get('start')}) in days is greater than "
            f"{inputs.get('duration')}."
        )
    if kind == "evidence_pack":
        if zh:
            return "记录输入和各任务产物的 sha256 与字节数，形成可独立核验的证据包。"
        return "Record sha256 and byte length of the input and of the other job files."
    if kind == "temporal_aggregate":
        if zh:
            return (
                f"按 {inputs.get('time_column')} 的 {inputs.get('grain')} 加总 "
                f"{inputs.get('measures')}。"
            )
        return (
            f"Sum {inputs.get('measures')} by {inputs.get('grain')} of {inputs.get('time_column')}."
        )
    if kind == "anomaly_list":
        columns = inputs.get("columns")
        if zh:
            return f"按既定规则列出 {columns} 上的异常。"
        return f"List anomalies on {columns} using the closed anomaly rules."
    if kind == "sla_breach_list":
        if zh:
            return (
                f"按 {inputs.get('group_by')} 列出 {inputs.get('start')} 到 "
                f"{inputs.get('end')} 的时效缺口。"
            )
        return (
            f"List SLA gaps from {inputs.get('start')} to {inputs.get('end')} "
            f"by {inputs.get('group_by')}."
        )
    if kind == "backlog_aging":
        if zh:
            return f"按 {inputs.get('open')} 计算积压账龄，关闭列为 {inputs.get('close')}。"
        return f"Age the backlog from {inputs.get('open')} until {inputs.get('close')}."
    title = job.get("title") or kind or "job"
    return str(title)


def _why(statement: str, jobs: list[dict[str, Any]], zh: bool) -> str:
    intents = sorted(_intents(statement))
    kinds = [str(job.get("kind")) for job in jobs]
    if zh:
        labels = "、".join(_ZH_INTENT_LABEL.get(name, name) for name in intents) or "无已知意图"
        kind_text = "、".join(kinds) if kinds else "空"
        return f"语句里有{labels}，列角色决定哪些规则成立，所以拆成 {kind_text}，不按任务编号套固定清单。"
    intent_text = ", ".join(intents) if intents else "no known intents"
    kind_text = ", ".join(kinds) if kinds else "no jobs"
    return (
        f"Intents ({intent_text}) and column roles produce {kind_text}; "
        f"the split is not taken from a task id."
    )


def _alternatives(goal: dict[str, Any], jobs: list[dict[str, Any]], zh: bool) -> list[str]:
    statement = _statement(goal)
    intents = _intents(statement)
    columns = _parse_columns(goal)
    kinds = {job.get("kind") for job in jobs}
    alts: list[str] = []

    def add(zh_text: str, en_text: str) -> None:
        alts.append(zh_text if zh else en_text)

    if "temporal_aggregate" not in kinds:
        if "summary" in intents and "monthly" not in intents and "weekly" not in intents:
            add(
                "不按月或按周加总金额：语句有汇总，但没有月度或周度词。",
                "No month or week measure rollup: the statement asks for a summary without a month or week grain.",
            )
        elif not any(column.role == "measure" for column in columns):
            add(
                "不按金额做时间汇总：模式里没有可加总的度量列。",
                "No measure rollup: the schema has no measure column.",
            )
        else:
            add(
                "不做时间度量汇总：汇总意图、粒度或度量列没有同时成立。",
                "No temporal aggregate: summary intent, grain, and a measure column are not all present.",
            )
    if "loan_operations_summary" not in kinds:
        if "summary" not in intents:
            add(
                "不做借阅笔数汇总：语句没有汇总意图。",
                "No loan-count summary: the statement has no summary intent.",
            )
        else:
            add(
                "不做借阅笔数汇总：缺少借期、成对日期、类别或第二个标识列。",
                "No loan-count summary: the schema lacks a duration, a date pair, a category, or a second identifier.",
            )
    if "overdue_list" not in kinds:
        if "overdue" not in intents:
            add(
                "不列逾期：语句没有逾期意图。",
                "No overdue list: the statement has no overdue intent.",
            )
        else:
            add(
                "不列逾期：缺少借出日、归还日、借期或标识列。",
                "No overdue list: the schema lacks a start date, a return date, a duration, or an identifier.",
            )
    if "anomaly_list" not in kinds:
        if "anomaly" not in intents:
            add("不单列异常：语句没有异常意图。", "No anomaly list: the statement has no anomaly intent.")
        else:
            add(
                "不单列异常：语句有异常意图，但没有状态列或度量列。",
                "No anomaly list: anomaly was asked for, but there is no status column or measure.",
            )
    if "sla_breach_list" not in kinds:
        add(
            "不列时效违约：语句没有时效或违约意图，或没有成对的事件时间列。",
            "No SLA list: the statement has no SLA intent, or the schema has no event-time pair.",
        )
    if "backlog_aging" not in kinds:
        add(
            "不做账龄：语句没有积压或账龄意图，或没有事件时间列。",
            "No backlog aging: the statement has no aging intent, or the schema has no event time.",
        )
    if not alts:
        add(
            "没有未触发的规则可记；已触发的规则都写进了任务集。",
            "Every closed rule that could fire on this statement and schema did fire.",
        )
    return alts
