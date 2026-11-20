#!/usr/bin/env python3
"""DS-P1-20261120 deterministic scorecard pipeline. Stdlib only, no network."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median

UTC = timezone.utc
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
NEED = ("cycle", "sha_full", "status", "ts_utc")


class PErr(Exception):
    def __init__(self, msg, src=None, line=None):
        self.src, self.line = src, line
        prefix = f"{src}:{line}: " if src and line is not None else (f"{src}: " if src else "")
        super().__init__(prefix + msg)


def parse_utc(value, src, line):
    if not isinstance(value, str):
        raise PErr(f"timestamp is not a string: {value!r}", src, line)
    try:
        return datetime.strptime(value, TIME_FMT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise PErr(f"invalid UTC timestamp {value!r}", src, line) from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dumps(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def field_lines(text: str) -> dict:
    out = {}
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r'\s*"([^"]+)"\s*:', line)
        if m and m.group(1) not in out:
            out[m.group(1)] = i
    return out


def load_obj(path: Path):
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PErr(f"invalid JSON: {exc.msg}", path.name, exc.lineno or 1) from exc
    if not isinstance(data, dict):
        raise PErr("expected a JSON object", path.name, 1)
    return data, field_lines(text)


def load_jsonl(path: Path):
    rows = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.strip() == "":
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PErr(f"invalid JSON: {exc.msg}", path.name, i) from exc
        if not isinstance(obj, dict):
            raise PErr("expected a JSON object", path.name, i)
        rows.append((i, obj))
    if not rows:
        raise PErr("no records found", path.name, 1)
    return rows


def cost_zero(value) -> bool:
    try:
        return value is not None and Decimal(str(value)) == 0
    except Exception:
        return False


def inc_time(rec, src, line):
    ts = rec.get("detected_utc", rec.get("detected_at_utc"))
    if ts is None:
        raise PErr("missing detected_utc / detected_at_utc", src, line)
    return parse_utc(ts, src, line)


def src(file, line, field=None, **extra):
    item = {"file": file}
    if line is not None:
        item["line"] = line
    if field is not None:
        item["field"] = field
    item.update(extra)
    return item


def span(file, lines, field=None):
    item = {"file": file, "lines": lines, "line": lines[0] if lines else None}
    if field:
        item["field"] = field
    if lines:
        item["line_start"], item["line_end"] = lines[0], lines[-1]
    return item


def compute(summary, slines, timeline, incidents, names):
    sn, tn, inn = names["summary"], names["timeline"], names["incidents"]
    for key in ("t0_utc", "t_end_utc", "planned_s"):
        if key not in summary:
            raise PErr(f"missing field {key}", sn, 1)
    t0_l, tend_l, plan_l = slines.get("t0_utc", 1), slines.get("t_end_utc", 1), slines.get("planned_s", 1)
    t0 = parse_utc(summary["t0_utc"], sn, t0_l)
    t_end = parse_utc(summary["t_end_utc"], sn, tend_l)
    try:
        planned_s = int(summary["planned_s"])
    except (TypeError, ValueError) as exc:
        raise PErr(f"planned_s is not an integer: {summary['planned_s']!r}", sn, plan_l) from exc
    if planned_s <= 0:
        raise PErr(f"planned_s must be positive: {planned_s}", sn, plan_l)
    wall_s = int((t_end - t0).total_seconds())
    declared = summary.get("wall_elapsed_s")
    wall_l = slines.get("wall_elapsed_s")
    if declared is not None and int(declared) != wall_s:
        raise PErr(f"wall_elapsed_s {declared} != t_end_utc-t0_utc {wall_s}", sn, wall_l or 1)

    parsed = []
    for line, rec in timeline:
        miss = [k for k in NEED if k not in rec]
        if miss:
            raise PErr(f"missing field(s) {', '.join(miss)}", tn, line)
        actual = parse_utc(rec["ts_utc"], tn, line)
        plan = parse_utc(rec["plan_wake"], tn, line) if rec.get("plan_wake") else None
        parsed.append({"line": line, "rec": rec, "actual": actual, "plan": plan})
    parsed.sort(key=lambda r: (r["actual"], r["rec"]["cycle"], r["line"]))
    if len(parsed) < 2:
        raise PErr("need at least two timeline records to infer cadence", tn, parsed[0]["line"])
    intervals = [(parsed[i]["actual"] - parsed[i - 1]["actual"]).total_seconds() for i in range(1, len(parsed))]
    cadence_s = int(median(intervals))
    threshold_s = max(600, cadence_s + 600)
    inc = [{"line": line, "rec": rec, "ts": inc_time(rec, inn, line)} for line, rec in incidents]

    clock_basis = summary.get("clock_basis") if isinstance(summary.get("clock_basis"), str) and summary.get("clock_basis").strip() else "utc_wall"
    verified = [r for r in parsed if r["rec"].get("status") == "VERIFIED"]
    verified_n = len(verified)
    exact = cadence_s > 0 and planned_s % cadence_s == 0
    expected_n = (planned_s // cadence_s) if cadence_s else 0
    expected_rule = "planned_s / cadence_s (exact integer)" if exact else "floor(planned_s / cadence_s)"
    f2 = (verified_n / expected_n) if expected_n else None

    unexplained_gaps, explained_gaps = [], []
    for i in range(1, len(parsed)):
        gap = intervals[i - 1]
        if gap <= threshold_s:
            continue
        start, end = parsed[i - 1]["actual"], parsed[i]["actual"]
        hits = [x for x in inc if start < x["ts"] <= end]
        item = {
            "from_cycle": parsed[i - 1]["rec"]["cycle"], "to_cycle": parsed[i]["rec"]["cycle"],
            "from_line": parsed[i - 1]["line"], "to_line": parsed[i]["line"], "gap_s": gap,
            "incident_lines": [h["line"] for h in hits],
        }
        (explained_gaps if hits else unexplained_gaps).append(item)

    cycle_v, sha_v = defaultdict(list), defaultdict(list)
    for r in verified:
        cycle_v[r["rec"]["cycle"]].append(r["line"])
        sha_v[str(r["rec"]["sha_full"])].append((r["rec"]["cycle"], r["line"]))
    dup_cycles = {str(k): v for k, v in cycle_v.items() if len(v) > 1}
    reused = {k: v for k, v in sha_v.items() if len({c for c, _ in v}) > 1}

    explained_dev, unexplained_dev = [], []
    with_plan = attr_n = 0
    for row in parsed:
        if row["plan"] is None:
            continue
        with_plan += 1
        dev = (row["actual"] - row["plan"]).total_seconds()
        if dev == 0:
            ok, inc_lines = True, []
        else:
            lo, hi = (row["plan"], row["actual"]) if row["plan"] <= row["actual"] else (row["actual"], row["plan"])
            hits = [x for x in inc if lo <= x["ts"] <= hi]
            ok, inc_lines = bool(hits), [h["line"] for h in hits]
        item = {"cycle": row["rec"]["cycle"], "line": row["line"], "deviation_s": dev, "incident_lines": inc_lines}
        if ok:
            attr_n += 1
            if dev:
                explained_dev.append(item)
        else:
            unexplained_dev.append(item)
    f9 = (attr_n / with_plan) if with_plan else None

    cost_present = "total_cost_cny" in summary
    calls_present = "model_calls" in summary
    cost_val, calls_val = summary.get("total_cost_cny"), summary.get("model_calls")
    zero = cost_present and cost_zero(cost_val)
    if not cost_present:
        c1, c1_note = None, "total_cost_cny missing; consistency not decidable"
    elif not zero:
        c1, c1_note = None, "total_cost_cny is not 0; C1 only constrains the zero-cost case"
    else:
        c1 = calls_present and calls_val == 0
        c1_note = "total_cost_cny=0 and model_calls=0" if c1 else "total_cost_cny=0 but model_calls is missing or not 0"

    t_lines = [r["line"] for r in parsed]
    v_lines = [r["line"] for r in verified]
    i_lines = [x["line"] for x in inc]
    plan_lines = [r["line"] for r in parsed if r["plan"] is not None]
    f1 = wall_s / planned_s

    scorecard = {
        "task_id": "DS-P1-20261120",
        "input_files": {"soak_summary.json": sn, "soak_timeline.jsonl": tn, "incidents.jsonl": inn},
        "metrics": {
            "F1": {
                "id": "F1", "name": "wall_clock_achievement_rate", "value": f1,
                "wall_elapsed_s": wall_s, "planned_s": planned_s, "clock_basis": clock_basis,
                "monotonic_elapsed_s": None, "t0_utc": summary["t0_utc"], "t_end_utc": summary["t_end_utc"],
                "note": "wall_elapsed_s recomputed as t_end_utc - t0_utc on UTC wall; package has no monotonic clock, so monotonic_elapsed_s is null",
            },
            "F2": {
                "id": "F2", "name": "effective_cycle_rate", "value": f2,
                "verified_cycles": verified_n, "expected_cycles": expected_n,
                "cadence_s": cadence_s, "expected_rule": expected_rule,
            },
            "F3": {
                "id": "F3", "name": "unexplained_gap_count", "value": len(unexplained_gaps),
                "cadence_s": cadence_s, "threshold_s": threshold_s,
                "threshold_rule": "max(600, cadence_s + 600)",
                "explained_gap_count": len(explained_gaps), "unexplained_gaps": unexplained_gaps,
            },
            "F6": {
                "id": "F6", "name": "hash_uniqueness",
                "duplicate_verified_cycle_count": len(dup_cycles),
                "reused_sha_full_count": len(reused),
                "duplicate_verified_cycles": dup_cycles,
                "reused_sha_full": {sha: {"cycles": [c for c, _ in pairs], "lines": [ln for _, ln in pairs]} for sha, pairs in reused.items()},
            },
            "F9": {
                "id": "F9", "name": "plan_actual_explainability_rate", "value": f9,
                "cycles_with_plan_wake": with_plan, "attributable_cycles": attr_n,
                "unexplained_deviation_count": len(unexplained_dev),
                "nonzero_explained_deviations": explained_dev,
                "unexplained_deviations": unexplained_dev,
                "rule": "denominator=cycles with plan_wake; attributable if deviation_s==0 or an incident detected_utc/detected_at_utc falls in the closed [plan_wake, actual ts_utc] interval (order-insensitive)",
            },
            "C1": {
                "id": "C1", "name": "cost_declaration_consistency", "value": c1,
                "total_cost_cny": cost_val, "model_calls": calls_val,
                "cost_is_zero": zero, "model_calls_present": calls_present, "note": c1_note,
            },
        },
    }
    inc_span = [span(inn, i_lines, "detected_utc")] if i_lines else []
    fields = {
        "metrics.F1.value": {"value": f1, "sources": [src(sn, t0_l, "t0_utc"), src(sn, tend_l, "t_end_utc"), src(sn, plan_l, "planned_s")]},
        "metrics.F1.wall_elapsed_s": {"value": wall_s, "sources": [src(sn, t0_l, "t0_utc"), src(sn, tend_l, "t_end_utc")] + ([src(sn, wall_l, "wall_elapsed_s")] if wall_l else [])},
        "metrics.F1.planned_s": {"value": planned_s, "sources": [src(sn, plan_l, "planned_s")]},
        "metrics.F1.monotonic_elapsed_s": {"value": None, "sources": [src(sn, slines.get("clock_basis", 1), "clock_basis", note="no monotonic timestamp fields exist in the sealed T7 package; left null rather than invented")]},
        "metrics.F2.value": {"value": f2, "sources": [span(tn, v_lines, "status"), src(sn, plan_l, "planned_s"), span(tn, t_lines, "ts_utc")]},
        "metrics.F2.verified_cycles": {"value": verified_n, "sources": [span(tn, v_lines, "status")]},
        "metrics.F2.expected_cycles": {"value": expected_n, "sources": [src(sn, plan_l, "planned_s"), span(tn, t_lines, "ts_utc")]},
        "metrics.F2.cadence_s": {"value": cadence_s, "sources": [span(tn, t_lines, "ts_utc")]},
        "metrics.F3.value": {"value": len(unexplained_gaps), "sources": [span(tn, t_lines, "ts_utc")] + inc_span},
        "metrics.F3.cadence_s": {"value": cadence_s, "sources": [span(tn, t_lines, "ts_utc")]},
        "metrics.F3.threshold_s": {"value": threshold_s, "sources": [span(tn, t_lines, "ts_utc")]},
        "metrics.F3.explained_gap_count": {"value": len(explained_gaps), "sources": [span(tn, t_lines, "ts_utc")] + inc_span},
        "metrics.F6.duplicate_verified_cycle_count": {"value": len(dup_cycles), "sources": [span(tn, v_lines, "cycle")]},
        "metrics.F6.reused_sha_full_count": {"value": len(reused), "sources": [span(tn, v_lines, "sha_full")]},
        "metrics.F9.value": {"value": f9, "sources": [span(tn, plan_lines, "plan_wake"), span(tn, t_lines, "ts_utc")] + inc_span},
        "metrics.F9.cycles_with_plan_wake": {"value": with_plan, "sources": [span(tn, plan_lines, "plan_wake")]},
        "metrics.F9.attributable_cycles": {"value": attr_n, "sources": [span(tn, t_lines, "ts_utc")] + inc_span},
        "metrics.F9.unexplained_deviation_count": {"value": len(unexplained_dev), "sources": [span(tn, t_lines, "ts_utc")] + inc_span},
        "metrics.C1.value": {"value": c1, "sources": [src(sn, slines.get("total_cost_cny", 1), "total_cost_cny"), src(sn, slines.get("model_calls", 1), "model_calls")]},
        "metrics.C1.model_calls": {"value": calls_val, "sources": [src(sn, slines.get("model_calls", 1), "model_calls")]},
    }
    if explained_dev or unexplained_dev:
        fields["metrics.F9.nonzero_deviations"] = {
            "value": len(explained_dev) + len(unexplained_dev),
            "sources": [src(tn, it["line"], "ts_utc", cycle=it["cycle"], deviation_s=it["deviation_s"], incident_lines=it["incident_lines"]) for it in explained_dev + unexplained_dev],
        }

    def walk(obj, path, acc):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}", acc)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]", acc)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            acc.append((path, obj))

    def sources_for(path, val):
        for key, rows, file, field in (
            ("nonzero_explained_deviations", explained_dev, tn, "ts_utc"),
            ("unexplained_deviations", unexplained_dev, tn, "ts_utc"),
            ("unexplained_gaps", unexplained_gaps, tn, "ts_utc"),
            ("explained_gaps", explained_gaps, tn, "ts_utc"),
        ):
            m = re.search(rf"{key}\[(\d+)\]", path)
            if not m:
                continue
            it = rows[int(m.group(1))]
            if "incident_lines[" in path:
                return [src(inn, int(val), "detected_utc")]
            if key.endswith("gaps") and path.endswith("from_line"):
                return [src(file, it["from_line"], "ts_utc")]
            if key.endswith("gaps") and path.endswith("to_line"):
                return [src(file, it["to_line"], "ts_utc")]
            return [src(file, it.get("line", it.get("from_line")), field, cycle=it.get("cycle", it.get("from_cycle")))]
        if path.startswith("metrics.F1"):
            return [src(sn, t0_l, "t0_utc"), src(sn, tend_l, "t_end_utc"), src(sn, plan_l, "planned_s")]
        if path.startswith("metrics.C1"):
            return [src(sn, slines.get("total_cost_cny", 1), "total_cost_cny"), src(sn, slines.get("model_calls", 1), "model_calls")]
        return [span(tn, t_lines, "ts_utc")] + inc_span

    nums = []
    walk(scorecard["metrics"], "metrics", nums)
    for path, val in nums:
        if path not in fields:
            fields[path] = {"value": val, "sources": sources_for(path, val)}
    provenance = {
        "task_id": "DS-P1-20261120",
        "coverage_rule": "every numeric field in scorecard.metrics maps to source file + line numbers",
        "fields": fields,
    }
    return scorecard, provenance


def write_outputs(out_dir: Path, scorecard, provenance, pipeline_path: Path, generated_utc: str, extra: dict):
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {"scorecard.json": dumps(scorecard), "provenance.json": dumps(provenance)}
    for name, data in artifacts.items():
        (out_dir / name).write_bytes(data)
    files_sha = {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()}
    for name, path in extra.items():
        if path.exists():
            files_sha[name] = sha256_file(path)
    files_sha["pipeline.py"] = sha256_file(pipeline_path)
    manifest = {
        "task_id": "DS-P1-20261120",
        "generated_utc": generated_utc,
        "code_sha": files_sha["pipeline.py"],
        "code_sha_spec": "sha256 of pipeline.py bytes",
        "files": files_sha,
        "model_calls": 0,
        "total_cost_cny": 0,
    }
    (out_dir / "manifest.json").write_bytes(dumps(manifest))
    return files_sha


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DS-P1-20261120 deterministic T7 scorecard pipeline")
    ap.add_argument("--summary", required=True, type=Path)
    ap.add_argument("--timeline", required=True, type=Path)
    ap.add_argument("--incidents", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--generated-utc", default=None, help="optional RFC3339 UTC for manifest only")
    ap.add_argument("--readme", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        for label, path in (("summary", args.summary), ("timeline", args.timeline), ("incidents", args.incidents)):
            if not path.is_file():
                raise PErr(f"{label} file not found: {path}", str(path))
        summary, slines = load_obj(args.summary)
        timeline, incidents = load_jsonl(args.timeline), load_jsonl(args.incidents)
        names = {"summary": args.summary.name, "timeline": args.timeline.name, "incidents": args.incidents.name}
        scorecard, provenance = compute(summary, slines, timeline, incidents, names)
        generated_utc = args.generated_utc or datetime.now(UTC).strftime(TIME_FMT)
        extra = {}
        if args.readme:
            extra["README.md"] = args.readme
        elif (args.out / "README.md").exists():
            extra["README.md"] = args.out / "README.md"
        write_outputs(args.out, scorecard, provenance, Path(__file__).resolve(), generated_utc, extra)
    except PErr as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
