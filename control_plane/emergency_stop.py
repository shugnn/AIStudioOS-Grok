"""File-based emergency stop (human kill switch, $0).

If the stop file exists, runners and `python -m control_plane run` must
refuse new work. Create the file to stop; delete it to clear. Optional
text body is reason.

Default path: docs/progress/EMERGENCY_STOP
Override: environment AISTUDIOOS_EMERGENCY_STOP (absolute or relative path).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STOP_PATH = ROOT / "docs" / "progress" / "EMERGENCY_STOP"
STOP_ENV = "AISTUDIOOS_EMERGENCY_STOP"


def stop_path() -> Path:
    override = os.environ.get(STOP_ENV)
    if override:
        return Path(override)
    return STOP_PATH


def is_stopped() -> bool:
    return stop_path().is_file()


def reason() -> str:
    path = stop_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[:500]
    except OSError:
        return "(unreadable)"


def status() -> dict:
    active = is_stopped()
    path = stop_path()
    return {
        "emergency_stop": active,
        "path": str(path),
        "reason": reason() if active else None,
    }


def arm(reason_text: str = "stop") -> Path:
    """Write the stop file. Runners must halt after this."""
    path = stop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (reason_text or "stop").strip() or "stop"
    path.write_text(text + "\n", encoding="utf-8")
    return path


def clear() -> bool:
    """Remove the stop file if present. Returns True if a file was removed."""
    path = stop_path()
    if path.is_file():
        path.unlink()
        return True
    return False
