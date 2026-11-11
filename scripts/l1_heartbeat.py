#!/usr/bin/env python3
"""L1 Heartbeat — local, zero paid API beyond existing GitHub PAT.

Syncs official DS rulings and task cards from Issue #9 comments before it
writes ``status_note``. Scans open issues, writes a timestamped artifact.
Does NOT execute Manager/Worker. Does NOT spend LLM budget.
Does NOT start the L2-2 clock or claim production 7×24.
Does NOT stop grok.com / grok-by-xai from posting its own notes.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ds_issue9

OUT_DIR = ROOT / "docs" / "progress"
OUT_DIR.mkdir(parents=True, exist_ok=True)

REPOS = [
    ("grok", "shugnn/AIStudioOS-Grok"),
    ("chatgpt", "shugnn/AIStudioOS-ChatGPT"),
]


def gh_get(url: str, token: str) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "AIStudioOS-Grok-L1-Heartbeat",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sync = ds_issue9.sync_issue9(None)
        print("GH_TOKEN required", file=sys.stderr)
        print(json.dumps(sync.to_dict(), ensure_ascii=False))
        return 2

    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y%m%d-%H%M%S")
    sync = ds_issue9.sync_issue9(token)
    inbox_ids = ds_issue9.inbox_task_ids(ROOT / "task_inbox")
    next_wake = (ts + timedelta(hours=1)).isoformat()
    note_rejected = None
    try:
        status_note = ds_issue9.build_heartbeat_note(
            sync,
            inbox_ids,
            utc=ts.isoformat(),
            next_wake=next_wake,
        )
    except ds_issue9.StaleNoteError as exc:
        status_note = None
        note_rejected = {"reason": exc.reason}
    report = {
        "type": "l1_heartbeat",
        "track": "AIStudioOS-Grok",
        "utc": ts.isoformat(),
        "repos": {},
        "blockers": [],
        "approval_needed": [],
        "notes": (
            "L1 scan only — no task execution, no LLM spend. "
            "status_note is gated on Issue #9 comment sync. "
            "This file does not stop grok.com / grok-by-xai from posting its own notes."
        ),
        "status_note": status_note,
        "note_rejected": note_rejected,
        "issue9_sync": sync.to_dict(),
        "task_entries": ds_issue9.task_entries(sync, inbox_ids),
        "production_7x24": ds_issue9.PRODUCTION_7X24,
    }

    for key, repo in REPOS:
        try:
            issues = gh_get(
                f"https://api.github.com/repos/{repo}/issues?state=open&per_page=30",
                token,
            )
            if not isinstance(issues, list):
                report["repos"][key] = {"error": str(issues)}
                continue
            # filter out PRs
            issues = [i for i in issues if "pull_request" not in i]
            summary = []
            for i in issues:
                labels = [l["name"] for l in i.get("labels", [])]
                item = {
                    "number": i["number"],
                    "title": i["title"][:100],
                    "labels": labels,
                    "updated_at": i.get("updated_at"),
                }
                summary.append(item)
                if "blocker" in labels:
                    report["blockers"].append(f"{key}#{i['number']}")
                if "approval-needed" in labels:
                    report["approval_needed"].append(f"{key}#{i['number']}")
            report["repos"][key] = {
                "open_issues": len(summary),
                "issues": summary,
            }
        except Exception as e:
            report["repos"][key] = {"error": str(e)}

    out = OUT_DIR / f"heartbeat-{ts_str}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Wrote {out}")
    print(json.dumps({
        "utc": report["utc"],
        "blockers": report["blockers"],
        "approval_needed": report["approval_needed"],
        "counts": {k: v.get("open_issues", v.get("error")) for k, v in report["repos"].items()},
        "status_note": report["status_note"],
        "note_rejected": report["note_rejected"],
        "issue9_sync_ok": sync.ok,
        "issue9_sync_error": sync.error_code,
        "production_7x24": ds_issue9.PRODUCTION_7X24,
    }, indent=2))
    if note_rejected is not None or not sync.ok:
        return 1
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
