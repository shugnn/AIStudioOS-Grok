#!/usr/bin/env python3
"""Status line. Sync Issue #9 comments, then print one gated line.

Does not post to GitHub. Does not start the L2-2 clock. Does not claim
production 7×24. A missing token or API failure is printed as
``issue9_sync_failed`` and does not invent a ruling.

This script cannot stop grok.com / grok-by-xai from posting its own lines.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ds_issue9


def main() -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    sync = ds_issue9.sync_issue9(token)
    inbox_ids = ds_issue9.inbox_task_ids(ROOT / "task_inbox")
    now = datetime.now(timezone.utc)
    try:
        line = ds_issue9.build_status_line(
            sync,
            inbox_ids,
            utc=now.isoformat(),
            next_wake=(now + timedelta(hours=1)).isoformat(),
        )
    except ds_issue9.StaleNoteError as exc:
        print(
            json.dumps({"ok": False, "error": "stale_note", "reason": exc.reason}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 3
    print(line)
    if not sync.ok:
        return 2 if sync.error_code == "missing_token" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
