import subprocess, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sample.txt"
sys.path.insert(0, str(ROOT))

from wcmini.core import count_file

def test_count_file_lines_words_bytes():
    l, w, b = count_file(FIX)
    assert l == 3
    assert w == 7
    assert b > 0

def test_count_empty(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("")
    l, w, b = count_file(f)
    assert l == 0 and w == 0 and b == 0

def test_cli_help():
    r = subprocess.run([sys.executable, "-m", "wcmini", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0
    assert "usage" in r.stdout.lower() or "word" in r.stdout.lower() or "wcmini" in r.stdout.lower()

def test_cli_on_fixture():
    r = subprocess.run([sys.executable, "-m", "wcmini", str(FIX)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0
    parts = r.stdout.split()
    assert int(parts[0]) == 3
    assert int(parts[1]) == 7

def test_cli_missing_file():
    r = subprocess.run([sys.executable, "-m", "wcmini", "no_such_file_xyz"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0

def test_version_import():
    import wcmini
    assert hasattr(wcmini, "__version__")
