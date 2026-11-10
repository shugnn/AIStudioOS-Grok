"""Deterministic, offline goal → job derivation.

Jobs are composed from statement intents and column roles. Nothing in this
module calls a network, an LLM, or a paid API.

This is evidence that a different goal plus a different input schema yields a
different job set. It does not grant or accept L2. Production 7×24 is
NOT ACCEPTED. The L2-2 72h clock is NOT STARTED.

The previous body of ``decompose`` returned ``[]`` for every input. Dispatch
titles on the orders cards were written onto those cards; this module does
not look them up and does not reproduce them on purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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

    Every other key is ignored. In particular, a card id or a file name
    cannot select a job list. The same statement tokens and the same
    columns always produce the same jobs. No rule matches → ``[]``.
    """

    def decompose(self, goal: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(goal, dict):
            raise TypeError("goal must be a dict")
        text = _statement(goal)
        intents = _intents(text)
        by_targets = _by_targets(text)
        columns = _parse_columns(goal)

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

        for index, job in enumerate(proposed, start=1):
            job["job_id"] = f"J{index}"

        evidence = _job_evidence(intents, columns, proposed)
        if evidence:
            proposed.append(evidence)
        return proposed


def get_decomposer() -> TaskDecomposer:
    return TaskDecomposer()


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
    return frozenset(
        name for name, vocab in _INTENT_TOKENS.items() if found & vocab
    )


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
