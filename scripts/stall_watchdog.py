#!/usr/bin/env python3
"""Detect stall: no fresh activity under progress dir within max_idle_minutes.

Modes:
  --summary PATH     legacy soak summary.jsonl (default: the soak_2h summary)
  --runner-glob      watch newest docs/progress/runner-*.json mtime (L1 duty)
  --alert PATH       where to write STALL_ALERT.json (default: docs/progress/)

Exit 0 healthy; 1 stall; 2 missing target.

The default summary is the live soak path used by a future duty. The committed
Ubuntu-24H files live on that same path today. The offline hook below does not
use that path. It classifies synthetic temp files only and does not start a
72h clock.

  python3 scripts/stall_watchdog.py --summary /tmp/fresh.jsonl --alert /tmp/STALL_ALERT.json
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "docs" / "progress" / "soak_2h" / "summary.jsonl"
PROGRESS = ROOT / "docs" / "progress"
ALERT = PROGRESS / "STALL_ALERT.json"
ENDED_SOAK_DIR = PROGRESS / "soak_2h"
PROBE_MAX_IDLE_MINUTES = 15.0
STALE_EXTRA_SECONDS = 60.0
SYNTHETIC_UTC = "2026-02-01T00:00:00Z"


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ended_soak_tree(path: Path) -> bool:
    """True when path is inside the committed soak_2h tree (Ubuntu-24H lives there)."""
    try:
        path.resolve().relative_to(ENDED_SOAK_DIR.resolve())
    except (OSError, ValueError):
        return False
    return True


def _summary_rows(summary: Path) -> tuple[int, str | None]:
    lines = summary.read_text(encoding="utf-8", errors="replace").splitlines()
    nrows = sum(1 for line in lines if line.strip())
    last_utc = None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            last_utc = str(json.loads(line).get("utc") or "") or None
        except json.JSONDecodeError:
            last_utc = None
        break
    return nrows, last_utc


def classify_summary(
    summary: Path,
    *,
    max_idle_minutes: float,
    now: float | None = None,
) -> dict:
    """Classify one summary by mtime. Does not write an alert and does not launch soak."""
    path_s = str(summary)
    now_s = time.time() if now is None else float(now)
    if not summary.is_file():
        return {"ok": False, "error": "summary_missing", "path": path_s, "utc": utc()}
    mtime = summary.stat().st_mtime
    nrows, last_utc = _summary_rows(summary)
    age_s = now_s - mtime
    max_s = float(max_idle_minutes) * 60.0
    stalled = age_s > max_s
    return {
        "ok": not stalled,
        "utc": utc(),
        "target": "summary",
        "path": path_s,
        "rows_or_files": nrows,
        "last_row_utc": last_utc,
        "file_age_seconds": round(age_s, 1),
        "max_idle_seconds": max_s,
        "stalled": stalled,
    }


def apply_alert(payload: dict, alert_path: Path) -> None:
    """Write or clear one alert file. A missing-target payload is left untouched."""
    if payload.get("error"):
        return
    if payload.get("stalled"):
        alert_path.parent.mkdir(parents=True, exist_ok=True)
        alert_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return
    if alert_path.is_file():
        try:
            alert_path.unlink()
        except OSError:
            pass


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def hook_classify(
    summary: Path,
    *,
    max_idle_minutes: float,
    alert_path: Path,
    now: float | None = None,
) -> tuple[int, dict]:
    """Offline-hook entry. Refuses the committed soak tree and the repo alert path.

    A refusal does not read the summary and does not write an alert. It is not
    a 72h result and it does not start a clock.
    """
    if ended_soak_tree(summary) or _same_file(summary, DEFAULT_SUMMARY):
        return 2, {
            "ok": False,
            "error": "ended_experiment_refused",
            "target": "summary",
            "path": str(summary),
            "ubuntu_24h_used_as_dut": True,
            "soak_launched": False,
            "clock_effect": "none",
            "utc": utc(),
        }
    if _same_file(alert_path, ALERT):
        return 2, {
            "ok": False,
            "error": "repo_alert_refused",
            "ubuntu_24h_used_as_dut": False,
            "soak_launched": False,
            "clock_effect": "none",
            "utc": utc(),
        }
    payload = classify_summary(summary, max_idle_minutes=max_idle_minutes, now=now)
    if payload.get("error"):
        return 2, payload
    apply_alert(payload, alert_path)
    return (1 if payload.get("stalled") else 0), payload


def _probe_failure(detail: str, *, repo_alert_written: bool = False) -> dict:
    return {
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
        "fresh_age_seconds": None,
        "stale_age_seconds": None,
        "gap_source": "operator_sample",
        "gap_appended": False,
        "gap_implies_soak_complete": False,
        "composed_with": "scripts/coverage_gap_log.py",
        "clock_effect": "none",
        "soak_launched": False,
        "binds_clock_start": False,
        "implies_l2_2_acceptance": False,
        "implies_72h_pass": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "repo_alert_written": repo_alert_written,
        "alert_left_in_repo": repo_alert_written,
        "max_idle_minutes": PROBE_MAX_IDLE_MINUTES,
        "stall_idle_seconds": PROBE_MAX_IDLE_MINUTES * 60.0,
        "detail": detail,
    }


def offline_probe(*, now: float | None = None) -> dict:
    """Classify a synthetic fresh summary and a synthetic stale summary.

    Uses temp files and a temp alert path. Does not open the committed soak_2h
    summary, does not write docs/progress/STALL_ALERT.json, does not launch
    soak_2h.py, and does not start the 72h clock.

    Bands for those ages come from coverage_gap_log. Nothing is appended.
    """
    try:
        import coverage_gap_log as gaplog
    except Exception as exc:
        return _probe_failure(f"gap_logger:{type(exc).__name__}")

    before_exists = ALERT.is_file()
    before_bytes = ALERT.read_bytes() if before_exists else None
    now_s = time.time() if now is None else float(now)
    max_s = PROBE_MAX_IDLE_MINUTES * 60.0
    fresh_intended = 0.0
    stale_intended = max_s + STALE_EXTRA_SECONDS
    line = json.dumps(
        {
            "utc": SYNTHETIC_UTC,
            "synthetic": True,
            "label": "scaffold",
            "evidence_class": "not_host",
        }
    )
    try:
        with tempfile.TemporaryDirectory(prefix="l2_2_stall_hook_") as tmp_name:
            tmp = Path(tmp_name)
            fresh = tmp / "fresh_summary.jsonl"
            stale = tmp / "stale_summary.jsonl"
            fresh_alert = tmp / "fresh_STALL_ALERT.json"
            stale_alert = tmp / "stale_STALL_ALERT.json"
            fresh.write_text(line + "\n", encoding="utf-8")
            stale.write_text(line + "\n", encoding="utf-8")
            os.utime(fresh, (now_s - fresh_intended, now_s - fresh_intended))
            os.utime(stale, (now_s - stale_intended, now_s - stale_intended))
            if ended_soak_tree(fresh) or ended_soak_tree(stale):
                return _probe_failure("synthetic_path_in_soak_tree")
            if _same_file(fresh, DEFAULT_SUMMARY) or _same_file(stale, DEFAULT_SUMMARY):
                return _probe_failure("default_summary")
            fresh_code, fresh_payload = hook_classify(
                fresh,
                max_idle_minutes=PROBE_MAX_IDLE_MINUTES,
                alert_path=fresh_alert,
                now=now_s,
            )
            stale_code, stale_payload = hook_classify(
                stale,
                max_idle_minutes=PROBE_MAX_IDLE_MINUTES,
                alert_path=stale_alert,
                now=now_s,
            )
            fresh_alert_exists = fresh_alert.is_file()
            stale_alert_exists = stale_alert.is_file()
            stale_alert_stalled = False
            if stale_alert_exists:
                try:
                    stale_doc = json.loads(stale_alert.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    stale_doc = {}
                stale_alert_stalled = stale_doc.get("stalled") is True
            fresh_age = fresh_payload.get("file_age_seconds")
            stale_age = stale_payload.get("file_age_seconds")
    except OSError as exc:
        return _probe_failure(f"probe_io:{type(exc).__name__}")

    after_exists = ALERT.is_file()
    after_bytes = ALERT.read_bytes() if after_exists else None
    repo_alert_written = (before_exists, before_bytes) != (after_exists, after_bytes)

    def _band(age: float) -> str:
        record = gaplog.build_record(
            gap_seconds=age,
            source="operator_sample",
            timestamp=SYNTHETIC_UTC,
        )
        if record.get("implies_soak_complete") is not False or record.get("clock_effect") != "none":
            raise RuntimeError("gap record overclaim")
        return str(record.get("band"))

    try:
        fresh_band = _band(fresh_intended)
        stale_band = _band(stale_intended)
        measured_fresh = gaplog.classify_band(fresh_age) if isinstance(fresh_age, (int, float)) else ""
        measured_stale = gaplog.classify_band(stale_age) if isinstance(stale_age, (int, float)) else ""
    except Exception as exc:
        return _probe_failure(f"gap_band:{type(exc).__name__}", repo_alert_written=repo_alert_written)

    ages_ok = (
        isinstance(fresh_age, (int, float))
        and not isinstance(fresh_age, bool)
        and fresh_age < gaplog.YELLOW_MIN_SECONDS
        and fresh_age <= max_s
        and isinstance(stale_age, (int, float))
        and not isinstance(stale_age, bool)
        and stale_age > gaplog.RED_MIN_SECONDS
        and stale_age > max_s
        and measured_fresh == fresh_band
        and measured_stale == stale_band
    )
    classified = (
        fresh_code == 0
        and fresh_payload.get("stalled") is False
        and fresh_payload.get("ok") is True
        and stale_code == 1
        and stale_payload.get("stalled") is True
        and stale_payload.get("ok") is False
        and fresh_alert_exists is False
        and stale_alert_exists is True
        and stale_alert_stalled is True
        and ages_ok
        and fresh_band == "ok"
        and stale_band == "red"
        and repo_alert_written is False
    )
    return {
        "ok": classified,
        "action": "synthetic_mtime",
        "tool": "scripts/stall_watchdog.py",
        "dut": "synthetic_temp_summary",
        "ubuntu_24h_used_as_dut": False,
        "default_summary_used": False,
        "fresh_stalled": fresh_payload.get("stalled") is True,
        "stale_stalled": stale_payload.get("stalled") is True,
        "fresh_exit": fresh_code,
        "stale_exit": stale_code,
        "fresh_gap_band": fresh_band,
        "stale_gap_band": stale_band,
        "fresh_age_seconds": fresh_age if isinstance(fresh_age, (int, float)) else None,
        "stale_age_seconds": stale_age if isinstance(stale_age, (int, float)) else None,
        "gap_source": "operator_sample",
        "gap_appended": False,
        "gap_implies_soak_complete": False,
        "composed_with": "scripts/coverage_gap_log.py",
        "clock_effect": "none",
        "soak_launched": False,
        "binds_clock_start": False,
        "implies_l2_2_acceptance": False,
        "implies_72h_pass": False,
        "production_7x24": "NOT_ACCEPTED",
        "can_start_clock": False,
        "can_accept_l2_2": False,
        "can_close_l2_2": False,
        "repo_alert_written": repo_alert_written,
        "alert_left_in_repo": repo_alert_written,
        "max_idle_minutes": PROBE_MAX_IDLE_MINUTES,
        "stall_idle_seconds": max_s,
        "detail": "synthetic_fresh_vs_stale" if classified else "classification_failed",
    }


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, default=None)
    ap.add_argument(
        "--runner-glob",
        action="store_true",
        help="watch newest runner-*.json under docs/progress (for L1 schtasks duty)",
    )
    ap.add_argument("--max-idle-minutes", type=float, default=PROBE_MAX_IDLE_MINUTES)
    ap.add_argument("--allow-missing", action="store_true")
    ap.add_argument(
        "--alert",
        type=Path,
        default=None,
        help="stall alert path (default: docs/progress/STALL_ALERT.json)",
    )
    args = ap.parse_args(argv)
    alert_path = args.alert if args.alert is not None else ALERT

    if args.runner_glob:
        target = "runner_glob"
        runners = sorted(PROGRESS.glob("runner-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not runners:
            payload = {"ok": False, "error": "no_runner_json", "utc": utc()}
            _emit(payload)
            return 0 if args.allow_missing else 2
        newest = runners[0]
        path_s = str(newest)
        mtime = newest.stat().st_mtime
        try:
            body = json.loads(newest.read_text(encoding="utf-8"))
            last_utc = str(body.get("utc") or "") or None
        except (OSError, json.JSONDecodeError):
            last_utc = None
        nrows = len(runners)
        age_s = time.time() - mtime
        max_s = args.max_idle_minutes * 60.0
        stalled = age_s > max_s
        payload = {
            "ok": not stalled,
            "utc": utc(),
            "target": target,
            "path": path_s,
            "rows_or_files": nrows,
            "last_row_utc": last_utc,
            "file_age_seconds": round(age_s, 1),
            "max_idle_seconds": max_s,
            "stalled": stalled,
        }
        _emit(payload)
        apply_alert(payload, alert_path)
        return 1 if stalled else 0

    summary = args.summary or DEFAULT_SUMMARY
    payload = classify_summary(summary, max_idle_minutes=args.max_idle_minutes)
    _emit(payload)
    if payload.get("error"):
        return 0 if args.allow_missing else 2
    apply_alert(payload, alert_path)
    return 1 if payload.get("stalled") else 0


if __name__ == "__main__":
    raise SystemExit(main())
