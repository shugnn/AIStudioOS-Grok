#!/usr/bin/env python3
"""Task entry check. Issue #9 comment cards and task_inbox/ together.

Prints the union. Does not execute a worker, start the L2-2 clock, or claim
production 7×24. A failed comment read leaves ``comment_cards_not_in_inbox``
null instead of pretending the queue was checked and was empty.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ds_issue9


def main() -> int:
    return ds_issue9.main(["--task-entry"])


if __name__ == "__main__":
    sys.exit(main())
