"""DS-T7-20261115 worker jobs: start or ensure the 72h soak daemons."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import t7_soak  # noqa: E402


def run(inbox, out, task_id):
    inbox = Path(inbox)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if task_id != "DS-T7-20261115":
        return {"ok": False, "error": "task_id_mismatch", "task_id": task_id}
    started = t7_soak.cmd_ensure()
    t7_soak.install_cron()
    status = t7_soak.cmd_status()
    (out / "start_status.json").write_text(
        json.dumps({"ensure": started, "status": status}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ok = bool(started.get("ok") and started.get("runner_pid") and started.get("guardian_pid"))
    return {
        "ok": ok,
        "task_id": task_id,
        "start_utc": started.get("start_utc"),
        "host": started.get("host"),
        "code_sha": started.get("code_sha"),
        "runner_pid": started.get("runner_pid"),
        "guardian_pid": started.get("guardian_pid"),
        "paid_api_called": False,
        "total_cost_cny": "0.00",
    }
