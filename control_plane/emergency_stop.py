"""File-based emergency stop (human kill switch, $0).

If docs/progress/EMERGENCY_STOP exists, runners must refuse new work.
Create the file to stop; delete it to clear. Optional text body is reason.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOP_PATH = ROOT / "docs" / "progress" / "EMERGENCY_STOP"


def is_stopped() -> bool:
    return STOP_PATH.is_file()


def reason() -> str:
    if not STOP_PATH.is_file():
        return ""
    try:
        return STOP_PATH.read_text(encoding="utf-8", errors="replace").strip()[:500]
    except OSError:
        return "(unreadable)"


def status() -> dict:
    active = is_stopped()
    return {
        "emergency_stop": active,
        "path": str(STOP_PATH),
        "reason": reason() if active else None,
    }
