from __future__ import annotations

import json
from pathlib import Path

import scripts.t7_soak as t7


def test_append_jsonl_idempotent(tmp_path, monkeypatch):
    p = tmp_path / "t.jsonl"
    assert t7.append_jsonl(p, {"idempotency_key": "k", "n": 1}, key="k")
    assert t7.append_jsonl(p, {"idempotency_key": "k", "n": 2}, key="k") is False
    lines = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["n"] == 1


def test_expected_appts_sha_constant():
    assert len(t7.EXPECTED_SHA) == 64
    assert t7.HEARTBEAT_SECONDS <= 10 * 60
    assert t7.DURATION_SECONDS == 72 * 3600
    assert t7.GUARD_POLL_SECONDS <= 10
