"""Emergency stop file semantics."""
from __future__ import annotations

import importlib
from pathlib import Path

import control_plane.emergency_stop as es


def test_stop_file_toggles(tmp_path, monkeypatch):
    stop = tmp_path / "EMERGENCY_STOP"
    monkeypatch.setattr(es, "STOP_PATH", stop)
    importlib.reload(es)
    monkeypatch.setattr(es, "STOP_PATH", stop)

    assert es.is_stopped() is False
    assert es.reason() == ""

    stop.write_text("founder halt", encoding="utf-8")
    assert es.is_stopped() is True
    assert "halt" in es.reason()
    st = es.status()
    assert st["emergency_stop"] is True

    stop.unlink()
    assert es.is_stopped() is False
