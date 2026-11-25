"""Emergency stop file semantics."""
from __future__ import annotations

import importlib
from pathlib import Path

import control_plane.emergency_stop as es


def test_stop_file_toggles(tmp_path, monkeypatch):
    stop = tmp_path / "EMERGENCY_STOP"
    monkeypatch.setenv(es.STOP_ENV, str(stop))
    monkeypatch.setattr(es, "STOP_PATH", stop)
    importlib.reload(es)
    monkeypatch.setenv(es.STOP_ENV, str(stop))
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


def test_arm_and_clear(tmp_path, monkeypatch):
    stop = tmp_path / "EMERGENCY_STOP"
    monkeypatch.setenv(es.STOP_ENV, str(stop))
    # re-bind module path users may still patch
    monkeypatch.setattr(es, "STOP_PATH", stop)

    assert es.is_stopped() is False
    path = es.arm("founder halt")
    assert path == stop
    assert es.is_stopped() is True
    assert "founder halt" in es.reason()
    assert es.status()["emergency_stop"] is True
    assert es.clear() is True
    assert es.is_stopped() is False
    assert es.clear() is False
