#!/usr/bin/env python3
"""DS-P4-20261123 P4-2: one-shot reject tests for three bad-input classes.

Drives a *copy* of the existing P1 pipeline.py (stdlib only). Never writes
into T7/P1 originals. Fixtures are built in a disposable directory.

Classes:
  1. missing_field   — drop ts_utc from one timeline record
  2. type_error      — set ts_utc of one timeline record to a JSON number
  3. time_regression — invert the soak window so t_end_utc < t0_utc,
                       leaving wall_elapsed_s as the original positive
                       duration. The P1 pipeline has no separate
                       "non-monotonic timeline" check (it re-sorts
                       records); an inverted summary window is the
                       existing reject surface, reported at file:line
                       via the wall-clock consistency check.

The process exits non-zero and prints a one-line summary `REJECT 3/3`
when all three classes are rejected, each with `文件:行号`, and no
partial products (scorecard.json / provenance.json / manifest.json)
are left in the disposable out dir.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Read-only originals. This script only copies them.
T7_DIR = Path("/workspace/t7-seal/sealed")
P1_PIPELINE = Path("/workspace/task_inbox_p1/pipeline.py")
PRODUCTS = ("scorecard.json", "provenance.json", "manifest.json")
FILE_LINE = re.compile(r"([^\s:]+\.[A-Za-z0-9]+):(\d+):")


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def copy_good(work: Path) -> dict[str, Path]:
    src = work / "src"
    src.mkdir()
    paths = {}
    for name in ("soak_summary.json", "soak_timeline.jsonl", "incidents.jsonl"):
        dest = src / name
        shutil.copy2(T7_DIR / name, dest)
        dest.chmod(0o644)
        paths[name] = dest
    pipe = work / "pipeline.py"
    shutil.copy2(P1_PIPELINE, pipe)
    pipe.chmod(0o644)
    paths["pipeline.py"] = pipe
    return paths


def mutate_timeline(src: Path, dest: Path, line_no: int, mutator) -> None:
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    if line_no < 1 or line_no > len(lines):
        die(f"timeline has no line {line_no}")
    raw = lines[line_no - 1]
    ended = raw.endswith("\n")
    rec = json.loads(raw)
    rec = mutator(rec)
    new = json.dumps(rec, ensure_ascii=False, separators=(", ", ": "))
    lines[line_no - 1] = new + ("\n" if ended else "")
    dest.write_text("".join(lines), encoding="utf-8")


def invert_window(src: Path, dest: Path) -> None:
    """Swap only the values of t0_utc and t_end_utc; leave other fields."""
    text = src.read_text(encoding="utf-8")
    t0 = re.search(r'"t0_utc"\s*:\s*"([^"]+)"', text)
    tend = re.search(r'"t_end_utc"\s*:\s*"([^"]+)"', text)
    if not t0 or not tend:
        die("summary is missing t0_utc or t_end_utc")
    a, b = t0.group(1), tend.group(1)
    if a == b:
        die("t0_utc and t_end_utc are identical; cannot invert")

    def sub_field(src_text: str, field: str, new_val: str) -> str:
        pat = re.compile(r'("' + field + r'"\s*:\s*")([^"]+)(")')
        m = pat.search(src_text)
        if not m:
            die(f"failed to rewrite {field}")
        return src_text[:m.start()] + m.group(1) + new_val + m.group(3) + src_text[m.end():]

    text = sub_field(text, "t0_utc", b)
    text = sub_field(text, "t_end_utc", a)
    dest.write_text(text, encoding="utf-8")


def run_pipeline(pipe: Path, summary: Path, timeline: Path, incidents: Path, out: Path) -> subprocess.CompletedProcess:
    out.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            sys.executable,
            str(pipe),
            "--summary", str(summary),
            "--timeline", str(timeline),
            "--incidents", str(incidents),
            "--out", str(out),
            "--generated-utc", "2026-11-23T07:00:00Z",
        ],
        capture_output=True,
        text=True,
    )


def leftover_products(out: Path) -> list[str]:
    found = []
    for name in PRODUCTS:
        p = out / name
        if p.exists():
            found.append(name)
            p.unlink()  # do not leave partial products behind
    return found


def judge(name: str, proc: subprocess.CompletedProcess, out: Path) -> dict:
    err = (proc.stderr or "") + (proc.stdout or "")
    m = FILE_LINE.search(err)
    products = leftover_products(out)
    rejected = proc.returncode != 0 and m is not None and not products
    # Collapse error to a single line for the transcript
    err_line = " | ".join(line.strip() for line in err.splitlines() if line.strip())
    return {
        "name": name,
        "rejected": rejected,
        "exit": proc.returncode,
        "file_line": f"{m.group(1)}:{m.group(2)}" if m else "",
        "error": err_line,
        "products": products,
    }


def main() -> int:
    if not T7_DIR.is_dir() or not P1_PIPELINE.is_file():
        die(f"required inputs not found: {T7_DIR} or {P1_PIPELINE}")

    # Line 11 is a mid-file VERIFIED record in the sealed timeline; used
    # for missing-field. Line 20 is a later record, used for type error.
    MISSING_LINE = 11
    TYPE_LINE = 20

    with tempfile.TemporaryDirectory(prefix="ds-p4-reject-") as td:
        work = Path(td)
        paths = copy_good(work)
        good_sum = paths["soak_summary.json"]
        good_tl = paths["soak_timeline.jsonl"]
        good_inc = paths["incidents.jsonl"]
        pipe = paths["pipeline.py"]
        fx = work / "fixtures"
        fx.mkdir()

        miss_tl = fx / "timeline_missing_field.jsonl"
        mutate_timeline(
            good_tl,
            miss_tl,
            MISSING_LINE,
            lambda rec: {k: v for k, v in rec.items() if k != "ts_utc"},
        )

        type_tl = fx / "timeline_type_error.jsonl"
        mutate_timeline(
            good_tl,
            type_tl,
            TYPE_LINE,
            lambda rec: {**rec, "ts_utc": 12345},
        )

        reg_sum = fx / "summary_time_regression.json"
        invert_window(good_sum, reg_sum)

        cases = [
            ("missing_field", good_sum, miss_tl, good_inc),
            ("type_error", good_sum, type_tl, good_inc),
            ("time_regression", reg_sum, good_tl, good_inc),
        ]

        results = []
        for name, summary, timeline, incidents in cases:
            out = work / "out" / name
            proc = run_pipeline(pipe, summary, timeline, incidents, out)
            rec = judge(name, proc, out)
            results.append(rec)
            products = ",".join(rec["products"]) if rec["products"] else "none"
            status = "REJECTED" if rec["rejected"] else "NOT_REJECTED"
            print(
                f"CASE {name}: {status} exit={rec['exit']} "
                f"file_line={rec['file_line'] or 'MISSING'} "
                f"products={products} error={rec['error']}"
            )

        n = sum(1 for r in results if r["rejected"])
        print(f"REJECT {n}/3")
        return 2 if n == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
