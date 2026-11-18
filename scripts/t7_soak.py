#!/usr/bin/env python3
"""DS-T7-20261115 72h unattended soak: runner + guardian + ensure."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TASK_ID = "DS-T7-20261115"
ROUND_SECONDS = 15 * 60
HEARTBEAT_SECONDS = 5 * 60
GUARD_POLL_SECONDS = 2
DURATION_SECONDS = 72 * 3600
EXPECTED_SHA = "a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28"
CRON_MARK = "# DS-T7-20261115"

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "task_inbox" / TASK_ID
OUT = INBOX / "deliverables"
APPTS = INBOX / "data" / "appts.csv"
PYTHON = Path("/home/shugnn/work/AIStudioOS-Grok/.venv/bin/python")
if not PYTHON.exists():
    PYTHON = Path(sys.executable)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def boot_id() -> str:
    p = Path("/proc/sys/kernel/random/boot_id")
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "unknown"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        pid = int(rec.get("pid") or 0)
    except Exception:
        return None
    return pid if pid_alive(pid) else None


def write_pid(path: Path, role: str) -> None:
    atomic_write(
        path,
        json.dumps(
            {"role": role, "pid": os.getpid(), "utc": utc_now(), "boot_id": boot_id()},
            indent=2,
        )
        + "\n",
    )


def append_jsonl(path: Path, obj: dict, key: str | None = None, field: str = "idempotency_key") -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if key is not None and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get(field) == key:
                return False
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return True


def load_summary() -> dict:
    p = OUT / "soak_summary.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_summary(s: dict) -> None:
    atomic_write(OUT / "soak_summary.json", json.dumps(s, indent=2, ensure_ascii=False) + "\n")


def record_incident(kind: str, attribution: str, message: str, extra: dict | None = None) -> None:
    if attribution not in {"business", "host", "supervision"}:
        attribution = "supervision"
    rec = {
        "utc": utc_now(),
        "kind": kind,
        "attribution": attribution,
        "message": message,
        "boot_id": boot_id(),
    }
    if extra:
        rec.update(extra)
    rec["idempotency_key"] = rec.get("idempotency_key") or f"{kind}:{rec['utc']}"
    append_jsonl(OUT / "incidents.jsonl", rec, key=rec["idempotency_key"])
    s = load_summary()
    s["restarts"] = int(s.get("restarts") or 0) + (1 if kind in {"runner_restart", "guardian_restart"} else 0)
    save_summary(s)


def git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (r.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def host_facts() -> dict:
    disk = {}
    try:
        u = shutil.disk_usage("/")
        disk = {"total": u.total, "used": u.used, "free": u.free}
    except Exception as exc:
        disk = {"error": str(exc)}
    load = None
    try:
        load = list(os.getloadavg())
    except Exception:
        pass
    ntp = None
    try:
        r = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            ntp = (r.stdout or "").strip()
    except Exception:
        pass
    return {
        "hostname": socket.gethostname(),
        "disk": disk,
        "loadavg": load,
        "ntp_synchronized": ntp,
        "boot_id": boot_id(),
    }


def productive_round(plan_wake: str, actual_wake: str, round_no: int) -> dict:
    facts = host_facts()
    sha = sha256_file(APPTS) if APPTS.exists() else ""
    hash_ok = sha == EXPECTED_SHA
    prev_ok = True
    timeline = OUT / "soak_timeline.jsonl"
    if timeline.exists():
        lines = [ln for ln in timeline.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            try:
                json.loads(lines[-1])
            except Exception:
                prev_ok = False
    deviation = abs(parse_utc(actual_wake) - parse_utc(plan_wake))
    explanation = ""
    if deviation > 2 * ROUND_SECONDS:
        explanation = f"plan/actual deviation {int(deviation)}s exceeds 2x interval"
    attribution_fail = None
    if not hash_ok:
        attribution_fail = "business"
        record_incident(
            "hash_mismatch",
            "business",
            f"appts.csv sha {sha} != expected",
            {"idempotency_key": f"hash:{plan_wake}"},
        )
    if not prev_ok:
        attribution_fail = attribution_fail or "business"
        record_incident(
            "timeline_corrupt",
            "business",
            "previous timeline line not readable",
            {"idempotency_key": f"timeline:{plan_wake}"},
        )
    result = "ok" if hash_ok and prev_ok else "fail"
    rec = {
        "utc": actual_wake,
        "plan_wake": plan_wake,
        "actual_wake": actual_wake,
        "action": "env_inspect_and_appts_hash",
        "result": result,
        "cost_cny": "0.00",
        "round": round_no,
        "idempotency_key": plan_wake,
        "appts_sha256": sha,
        "hash_ok": hash_ok,
        "prev_artifact_ok": prev_ok,
        "deviation_seconds": int(deviation),
        "explanation": explanation,
        "facts": facts,
    }
    written = append_jsonl(timeline, rec, key=plan_wake)
    s = load_summary()
    s["task_id"] = TASK_ID
    s["rounds"] = int(s.get("rounds") or 0) + (1 if written else 0)
    if written and result == "ok":
        s["effective_rounds"] = int(s.get("effective_rounds") or 0) + 1
    s["status"] = "running"
    s["total_cost_cny"] = "0.00"
    if s.get("start_utc"):
        s["wall_seconds"] = int(max(0, parse_utc(actual_wake) - parse_utc(s["start_utc"])))
    save_summary(s)
    rec["written"] = written
    rec["attribution_fail"] = attribution_fail
    return rec


def heartbeat() -> None:
    atomic_write(
        OUT / "heartbeat.json",
        json.dumps({"utc": utc_now(), "pid": os.getpid(), "boot_id": boot_id()}, indent=2) + "\n",
    )


def write_manifest(start_utc: str) -> None:
    atomic_write(
        OUT / "manifest.json",
        json.dumps(
            {
                "task_id": TASK_ID,
                "start_utc": start_utc,
                "host": socket.gethostname(),
                "code_sha": git_sha(),
                "appts_sha256": EXPECTED_SHA,
                "worktree": str(ROOT),
                "supervision": "task_inbox/DS-T7-20261115/SUPERVISION.md",
                "heartbeat_seconds": HEARTBEAT_SECONDS,
                "round_seconds": ROUND_SECONDS,
                "duration_seconds": DURATION_SECONDS,
                "cost_cap_cny": "1.00",
            },
            indent=2,
        )
        + "\n",
    )


def init_start() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    s = load_summary()
    if not s.get("start_utc"):
        s.update(
            {
                "start_utc": utc_now(),
                "end_utc": None,
                "wall_seconds": 0,
                "rounds": 0,
                "effective_rounds": 0,
                "gaps_over_10min": 0,
                "restarts": int(s.get("restarts") or 0),
                "interventions": 0,
                "total_cost_cny": "0.00",
                "status": "running",
                "task_id": TASK_ID,
                "host": socket.gethostname(),
                "start_boot_id": boot_id(),
            }
        )
        save_summary(s)
        write_manifest(s["start_utc"])
    return s


def detect_host_gap(s: dict) -> None:
    if s.get("start_boot_id") and s["start_boot_id"] != boot_id():
        key = f"reboot:{boot_id()}"
        record_incident(
            "host_reboot_or_boot_change",
            "host",
            "boot_id changed since start; auto-continuing",
            {"idempotency_key": key, "previous_boot_id": s.get("start_boot_id")},
        )
    hb = OUT / "heartbeat.json"
    if hb.exists():
        try:
            prev = json.loads(hb.read_text(encoding="utf-8")).get("utc")
            if prev:
                gap = time.time() - parse_utc(prev)
                if gap > 10 * 60:
                    key = f"gap:{prev}"
                    added = append_jsonl(
                        OUT / "incidents.jsonl",
                        {
                            "utc": utc_now(),
                            "kind": "gap_over_10min",
                            "attribution": "host" if gap > 30 * 60 else "supervision",
                            "message": f"heartbeat gap {int(gap)}s after {prev}; auto-continuing",
                            "gap_seconds": int(gap),
                            "idempotency_key": key,
                        },
                        key=key,
                    )
                    if added:
                        s = load_summary()
                        s["gaps_over_10min"] = int(s.get("gaps_over_10min") or 0) + 1
                        save_summary(s)
        except Exception:
            pass


def spawn(role: str) -> int:
    log = OUT / f"{role}.log"
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [str(PYTHON), str(ROOT / "scripts" / "t7_soak.py"), role]
    with log.open("a", encoding="utf-8") as f:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def ensure_role(role: str, pid_path: Path, record: bool = True) -> tuple[int, bool]:
    pid = read_pid(pid_path)
    if pid:
        return pid, False
    new_pid = spawn(role)
    if record:
        record_incident(
            f"{role}_restart",
            "supervision",
            f"{role} was down; spawned pid {new_pid}",
            {"idempotency_key": f"{role}_restart:{utc_now()}", "spawned_pid": new_pid},
        )
    for _ in range(20):
        time.sleep(0.2)
        live = read_pid(pid_path)
        if live:
            return live, True
    return new_pid, True


def cmd_ensure() -> dict:
    existed = (OUT / "runner.pid").exists() or (OUT / "guardian.pid").exists() or bool(load_summary().get("rounds"))
    init_start()
    detect_host_gap(load_summary())
    runner_pid, r_new = ensure_role("runner", OUT / "runner.pid", record=existed)
    guard_pid, g_new = ensure_role("guardian", OUT / "guardian.pid", record=existed)
    return {
        "ok": True,
        "runner_pid": runner_pid,
        "guardian_pid": guard_pid,
        "runner_spawned": r_new,
        "guardian_spawned": g_new,
        "start_utc": load_summary().get("start_utc"),
        "code_sha": git_sha(),
        "host": socket.gethostname(),
    }


def peer_pid(role: str) -> int | None:
    return read_pid(OUT / f"{role}.pid")


def maybe_respawn_peer(self_role: str) -> None:
    other = "guardian" if self_role == "runner" else "runner"
    if peer_pid(other) is None:
        pid, spawned = ensure_role(other, OUT / f"{other}.pid")
        if spawned:
            record_incident(
                f"{other}_killed_detected",
                "supervision",
                f"{self_role} detected {other} dead; respawned pid {pid}",
                {"idempotency_key": f"{other}_killed:{utc_now()}", "spawned_pid": pid},
            )


def finished(s: dict) -> bool:
    start = s.get("start_utc")
    if not start:
        return False
    return time.time() - parse_utc(start) >= DURATION_SECONDS


def finalize() -> None:
    s = load_summary()
    s["end_utc"] = utc_now()
    if s.get("start_utc"):
        s["wall_seconds"] = int(parse_utc(s["end_utc"]) - parse_utc(s["start_utc"]))
    s["status"] = "completed"
    s["total_cost_cny"] = "0.00"
    save_summary(s)


def cmd_runner() -> int:
    write_pid(OUT / "runner.pid", "runner")
    s = init_start()
    detect_host_gap(s)
    start_ts = parse_utc(s["start_utc"])
    # How many rounds already recorded?
    n = int(s.get("rounds") or 0)
    last_hb = 0.0
    while True:
        s = load_summary()
        if finished(s):
            finalize()
            return 0
        plan_ts = start_ts + n * ROUND_SECONDS
        now = time.time()
        if now >= plan_ts + ROUND_SECONDS:
            missed = int((now - plan_ts) // ROUND_SECONDS)
            record_incident(
                "missed_rounds",
                "host" if missed >= 2 else "supervision",
                f"missed {missed} full interval(s); skipping catch-up writes, jumping to current slot",
                {"idempotency_key": f"missed:{n}:{missed}", "from_round": n},
            )
            s = load_summary()
            s["gaps_over_10min"] = int(s.get("gaps_over_10min") or 0) + 1
            save_summary(s)
            n = int((now - start_ts) // ROUND_SECONDS)
            plan_ts = start_ts + n * ROUND_SECONDS
        if now >= plan_ts:
            actual = utc_now()
            plan = datetime.fromtimestamp(plan_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            productive_round(plan, actual, n)
            n = n + 1
            heartbeat()
            last_hb = time.time()
            maybe_respawn_peer("runner")
            continue
        if now - last_hb >= HEARTBEAT_SECONDS or last_hb == 0:
            heartbeat()
            last_hb = now
            maybe_respawn_peer("runner")
        sleep_for = min(1.0, max(0.1, plan_ts - time.time()))
        time.sleep(sleep_for)


def cmd_guardian() -> int:
    write_pid(OUT / "guardian.pid", "guardian")
    init_start()
    while True:
        s = load_summary()
        if finished(s):
            return 0
        maybe_respawn_peer("guardian")
        time.sleep(GUARD_POLL_SECONDS)


def cmd_status() -> dict:
    s = load_summary()
    return {
        "ok": True,
        "summary": s,
        "runner_pid": read_pid(OUT / "runner.pid"),
        "guardian_pid": read_pid(OUT / "guardian.pid"),
        "code_sha": git_sha(),
        "host": socket.gethostname(),
        "heartbeat": (OUT / "heartbeat.json").read_text(encoding="utf-8") if (OUT / "heartbeat.json").exists() else None,
    }


def install_cron() -> None:
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        text = cur.stdout if cur.returncode == 0 else ""
    except Exception:
        text = ""
    if CRON_MARK in text:
        return
    line_ensure = (
        f"*/5 * * * * {PYTHON} {ROOT / 'scripts' / 't7_soak.py'} ensure "
        f">> {OUT / 'cron.log'} 2>&1"
    )
    line_reboot = (
        f"@reboot sleep 20 && {PYTHON} {ROOT / 'scripts' / 't7_soak.py'} ensure "
        f">> {OUT / 'cron.log'} 2>&1"
    )
    new = text.rstrip() + ("\n" if text and not text.endswith("\n") else "")
    new += f"{CRON_MARK}\n{line_ensure}\n{line_reboot}\n"
    subprocess.run(["crontab", "-"], input=new, text=True, check=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "ensure"
    OUT.mkdir(parents=True, exist_ok=True)
    if cmd == "ensure":
        print(json.dumps(cmd_ensure(), ensure_ascii=False, indent=2))
        return 0
    if cmd == "runner":
        return cmd_runner()
    if cmd == "guardian":
        return cmd_guardian()
    if cmd == "status":
        print(json.dumps(cmd_status(), ensure_ascii=False, indent=2))
        return 0
    if cmd == "install-cron":
        install_cron()
        print(json.dumps({"ok": True, "cron": "installed"}))
        return 0
    print(json.dumps({"ok": False, "error": "unknown_cmd", "cmd": cmd}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
