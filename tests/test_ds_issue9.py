"""Issue #9 comment sync: rulings, task cards, and stale-note refusal."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ds_issue9


SIG = "—— 观察轨（DS）代发"

PRODUCT = f"""【产品级验收结论 · 2026-11-07】能力阶梯位置：L1 有条件通过，L2 未开始

**L1（调度 + 证据 + 监督）= CONDITIONAL ACCEPTED**
**L2（拆活 + Worker 实现）= NOT STARTED**

生产 7×24 仍 NOT ACCEPTED。
{SIG}
"""

L2_CONDITIONAL = f"""【L2 待证点核验 · Grok（PR #14）】**证据受理，L2 仍 CONDITIONAL（已接近）**

**结论**：L2 = CONDITIONAL，差最后一步。
{SIG}
"""

T2_CONDITIONAL = f"""【T2 核验 · Grok 轨（PR #13）】**CONDITIONAL —— 核心证据强，三处待补**

补齐上述三点可转 ACCEPTED。
{SIG}
"""

T2_FINAL = f"""【T2 最终裁定 · Grok 轨】**ACCEPTED（附一条能力说明）**；L2 判 **CONDITIONAL**

**T2 = ACCEPTED。**

**L2 判定：CONDITIONAL（不授予，但承认证据方向正确）**
{SIG}
"""

T3_CARD = f"""【正式任务卡 T3-20261111（盲测·冻结）】TASK ID：`DS-T3-20261111`

**一、目标（只给目标，不给拆法）**
{SIG}
"""

FORMAL = f"""【L2 裁定正式发布 + 流程缺陷提醒】观察轨 · 2026-11-11

**Grok 轨 T3 = ACCEPTED；L2（拆活 + Worker 实现）= ACCEPTED**

若日后发现 plan.json 实为手写代出，本裁定作废并按 REJECTED 处理。
你方心跳连续多轮仍写 `note=L1 done L2 pending`
生产 7×24 仍 NOT ACCEPTED。L2-2 72h 时钟仍 NOT STARTED。
L2-2 START: utc=<T0> sha=<完整SHA> host=<主机> max_wall_seconds=259200
{SIG}
"""

L2_2_APPROVAL = f"""【L2-2 批准（限定条件）】针对 PR #12：允许启动 72h 长测

创始人已批准。条件具备即启动，不必再等批准。
can_start_clock discussion is not a flag this helper sets.
L2-2 START: utc=<T0> sha=<完整SHA> host=<主机> max_wall_seconds=259200
{SIG}
"""

WORKER_PENDING = (
    "heartbeat utc=2026-11-11T15:15:00Z next_wake_utc=2026-11-11T16:15:00Z "
    "status=idle queue=empty note=L1 done L2 pending"
)

WORKER_WITH_SIGNATURE = (
    "heartbeat utc=2026-11-11T18:00:00Z note=L2 = REJECTED\n" + SIG
)


def _comment(body: str, *, cid: int, created_at: str) -> dict:
    return {"id": cid, "created_at": created_at, "body": body, "user": {"login": "shugnn"}}


def _chain() -> list[dict]:
    return [
        _comment(PRODUCT, cid=6703183836, created_at="2026-11-07T06:08:29Z"),
        _comment(T2_CONDITIONAL, cid=6763278495, created_at="2026-11-10T09:00:45Z"),
        _comment(L2_CONDITIONAL, cid=6767990189, created_at="2026-11-10T13:00:44Z"),
        _comment(T3_CARD, cid=6775337980, created_at="2026-11-10T18:11:16Z"),
        _comment(FORMAL, cid=6799203994, created_at="2026-11-11T14:58:11Z"),
        _comment(WORKER_PENDING, cid=6798192308, created_at="2026-11-11T14:15:34Z"),
        _comment(WORKER_WITH_SIGNATURE, cid=6799990001, created_at="2026-11-11T18:00:00Z"),
        _comment(L2_2_APPROVAL, cid=6761044915, created_at="2026-11-10T06:50:14Z"),
    ]


def test_latest_ruling_wins_even_if_comments_are_unsorted():
    comments = list(reversed(_chain()))
    sync = ds_issue9.parse_comments(comments)
    assert sync.ok is True
    assert sync.rulings["L2"].verdict == "ACCEPTED"
    assert sync.rulings["L2"].comment_id == 6799203994
    assert sync.rulings["T3"].verdict == "ACCEPTED"
    assert sync.rulings["T3"].comment_id == 6799203994
    assert sync.rulings["T2"].verdict == "CONDITIONAL"
    assert sync.rulings["L1"].verdict == "CONDITIONAL"
    assert "REJECTED" not in {item.verdict for item in sync.rulings.values()}
    assert "can_start_clock" not in sync.to_dict()

    later = comments + [
        _comment(
            f"【L2 裁定】 L2 = REJECTED\n{SIG}",
            cid=6800000001,
            created_at="2026-11-11T19:00:00Z",
        )
    ]
    updated = ds_issue9.parse_comments(later)
    assert updated.rulings["L2"].verdict == "REJECTED"
    assert updated.rulings["L2"].comment_id == 6800000001
    assert updated.rulings["T3"].verdict == "ACCEPTED"


def test_later_official_ruling_updates_the_note():
    early_comments = [
        _comment(PRODUCT, cid=1, created_at="2026-11-07T06:08:29Z"),
        _comment(L2_CONDITIONAL, cid=2, created_at="2026-11-10T13:00:44Z"),
    ]
    early = ds_issue9.parse_comments(early_comments)
    early_note = ds_issue9.build_heartbeat_note(early, [], utc="t0", next_wake="t1")
    assert "L2=CONDITIONAL" in early_note
    assert "L2=ACCEPTED" not in early_note
    assert "L1=CONDITIONAL" in early_note
    assert "L1=ACCEPTED" not in early_note

    late = ds_issue9.parse_comments(
        early_comments
        + [_comment(FORMAL, cid=3, created_at="2026-11-11T14:58:11Z")]
    )
    late_note = ds_issue9.build_heartbeat_note(late, [], utc="t0", next_wake="t1")
    assert "L2=ACCEPTED" in late_note
    assert "T3=ACCEPTED" in late_note
    assert "L2=CONDITIONAL" not in late_note
    assert "L2 pending" not in late_note
    assert "L2 not started" not in late_note
    assert late_note.startswith("heartbeat ")
    status = ds_issue9.build_status_line(late, [], utc="t0", next_wake="t1")
    assert status.startswith("status_line ")
    assert "L2=ACCEPTED" in status
    assert "L2=CONDITIONAL" not in status


def test_task_card_in_comments_is_detected_without_an_inbox_folder(tmp_path: Path):
    mention_only = _comment(
        f"而我方任务卡 `DS-T9-20261112` 已发在评论里。\n{SIG}",
        cid=10,
        created_at="2026-11-09T01:30:38Z",
    )
    worker_card = _comment(
        "【Worker 收件】收到正式题卡 TASK ID：`DS-T8-20261112`\nmain 上 task_inbox/ 尚无该目录。",
        cid=11,
        created_at="2026-11-10T18:28:10Z",
    )
    card = _comment("\ufeff" + T3_CARD, cid=6775337980, created_at="2026-11-10T18:11:16Z")
    sync = ds_issue9.parse_comments([mention_only, worker_card, card])
    assert [item.task_id for item in sync.task_cards] == ["DS-T3-20261111"]

    inbox = tmp_path / "task_inbox"
    (inbox / "DS-T1-20261108").mkdir(parents=True)
    inbox_ids = ds_issue9.inbox_task_ids(inbox)
    missing = ds_issue9.new_task_cards(sync, inbox_ids)
    assert [item.task_id for item in missing] == ["DS-T3-20261111"]

    entries = ds_issue9.task_entries(sync, inbox_ids)
    by_id = {row["task_id"]: row for row in entries}
    assert by_id["DS-T1-20261108"]["in_inbox"] is True
    assert by_id["DS-T1-20261108"]["in_issue_comment"] is False
    assert by_id["DS-T3-20261111"]["in_inbox"] is False
    assert by_id["DS-T3-20261111"]["in_issue_comment"] is True
    assert by_id["DS-T3-20261111"]["comment_id"] == 6775337980
    assert "DS-T9-20261112" not in by_id
    assert "DS-T8-20261112" not in by_id

    note = ds_issue9.build_heartbeat_note(sync, inbox_ids, utc="t0", next_wake="t1")
    assert "queue=has_task" in note
    assert "new_task_cards=DS-T3-20261111" in note
    assert "queue=empty" not in note
    with pytest.raises(ds_issue9.StaleNoteError) as raised:
        ds_issue9.prepare_note(
            "heartbeat utc=t queue=empty note=no new tasks",
            sync,
            inbox_ids,
        )
    assert raised.value.reason == "queue_empty_while_issue_task_card"


def test_stale_l2_pending_is_rejected_after_accepted():
    sync = ds_issue9.parse_comments(_chain())
    drafts = [
        "heartbeat utc=2026-11-11T14:15:00Z status=idle queue=empty note=L1 done L2 pending",
        "note=L2 not started",
        "note=L2未开始",
        "note=L1done L2notstart",
        "note=L1 done L2 idle",
    ]
    for draft in drafts:
        with pytest.raises(ds_issue9.StaleNoteError) as raised:
            ds_issue9.prepare_note(draft, sync, ["DS-T1-20261108"])
        assert raised.value.reason == "stale_l2_note_after_accepted"

    allowed = ds_issue9.build_heartbeat_note(
        sync,
        ["DS-T1-20261108", "DS-T3-20261111"],
        utc="t0",
        next_wake="t1",
    )
    assert ds_issue9.prepare_note(allowed, sync, ["DS-T1-20261108", "DS-T3-20261111"]) == allowed
    assert "L2 pending" not in allowed
    assert "can_start_clock" not in allowed
    assert "L2-2 START" not in allowed
    assert "production_7x24=NOT_ACCEPTED" in allowed
    assert "production_7x24=ACCEPTED" not in allowed

    with pytest.raises(ds_issue9.StaleNoteError):
        ds_issue9.prepare_note("note=L2=CONDITIONAL T3=ACCEPTED T2=CONDITIONAL L1=CONDITIONAL", sync, [])
    with pytest.raises(ds_issue9.StaleNoteError) as clock:
        ds_issue9.prepare_note(allowed + " can_start_clock=true", sync, [])
    assert clock.value.reason == "refusing_l2_2_start_or_clock_flag"


def test_missing_token_and_api_failure_do_not_invent_a_ruling():
    called = {"n": 0}

    def opener(req, timeout=30):
        called["n"] += 1
        raise AssertionError("must not call the API without a token")

    missing = ds_issue9.sync_issue9(None, opener=opener)
    blank = ds_issue9.sync_issue9("   ", opener=opener)
    assert called["n"] == 0
    for sync in (missing, blank):
        assert sync.ok is False
        assert sync.error_code == "missing_token"
        assert sync.rulings == {}
        assert sync.task_cards == []
        note = ds_issue9.build_heartbeat_note(sync, [], utc="t0", next_wake="t1")
        assert "issue9_sync_failed" in note
        assert "error=missing_token" in note
        assert "=ACCEPTED" not in note
        assert "=CONDITIONAL" not in note
        assert "=REJECTED" not in note
        assert "L2 pending" not in note
        assert "can_start_clock" not in note
        with pytest.raises(ds_issue9.StaleNoteError) as invented:
            ds_issue9.prepare_note("note=L2=ACCEPTED", sync, [])
        assert invented.value.reason == "sync_failed_would_invent_ruling"
        with pytest.raises(ds_issue9.StaleNoteError) as pending:
            ds_issue9.prepare_note("note=L2 pending", sync, [])
        assert pending.value.reason == "sync_failed_refusing_unverified_l2_status"

    def forbidden(req, timeout=30):
        raise urllib.error.HTTPError(
            req.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"resource not accessible"}'),
        )

    failed = ds_issue9.sync_issue9("token-value", opener=forbidden)
    assert failed.ok is False
    assert failed.error_code == "api_failure"
    assert "403" in (failed.error_detail or "")
    assert failed.rulings == {}
    assert failed.task_cards == []
    assert "token-value" not in (failed.error_detail or "")
    note = ds_issue9.build_heartbeat_note(failed, ["DS-T1-20261108"], utc="t0", next_wake="t1")
    assert "error=api_failure" in note
    assert "=ACCEPTED" not in note
    payload = failed.to_dict()
    assert payload["rulings"] == {}
    assert payload["task_cards"] == []
    assert payload["production_7x24"] == "NOT_ACCEPTED"
    assert "can_start_clock" not in payload

    def not_a_list(req, timeout=30):
        class Resp:
            def read(self):
                return b'{"message":"nope"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    bad = ds_issue9.sync_issue9("token-value", opener=not_a_list)
    assert bad.ok is False
    assert bad.error_code == "api_failure"
    assert bad.rulings == {}


def test_failed_later_page_does_not_keep_an_earlier_ruling():
    from urllib.parse import parse_qs, urlparse

    def opener(req, timeout=30):
        page = parse_qs(urlparse(req.full_url).query).get("page", ["1"])[0]
        if page == "1":
            batch = [
                _comment(L2_CONDITIONAL, cid=i, created_at="2026-11-10T13:00:44Z")
                for i in range(100)
            ]

            class Resp:
                def read(self):
                    return json.dumps(batch).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return Resp()
        raise urllib.error.URLError("timed out")

    sync = ds_issue9.sync_issue9("token-value", opener=opener)
    assert sync.ok is False
    assert sync.error_code == "api_failure"
    assert sync.rulings == {}
    assert sync.task_cards == []
    note = ds_issue9.build_heartbeat_note(sync, [], utc="t0", next_wake="t1")
    assert "L2=CONDITIONAL" not in note
    assert "L2=ACCEPTED" not in note
    assert "error=api_failure" in note


def test_not_started_void_clause_and_l2_2_do_not_grant_flags():
    only_product = ds_issue9.parse_comments(
        [_comment(PRODUCT, cid=1, created_at="2026-11-07T06:08:29Z")]
    )
    assert only_product.rulings["L1"].verdict == "CONDITIONAL"
    assert "L2" not in only_product.rulings
    ds_issue9.prepare_note("note=L1=CONDITIONAL L2 pending", only_product, [])

    t2 = ds_issue9.parse_comments(
        [_comment(T2_CONDITIONAL, cid=2, created_at="2026-11-10T09:00:45Z")]
    )
    assert t2.rulings["T2"].verdict == "CONDITIONAL"
    assert all(item.verdict != "ACCEPTED" for item in t2.rulings.values())

    t2_final = ds_issue9.parse_comments(
        [_comment(T2_FINAL, cid=6765608469, created_at="2026-11-10T11:00:40Z")]
    )
    assert t2_final.rulings["T2"].verdict == "ACCEPTED"
    assert t2_final.rulings["T2"].comment_id == 6765608469
    assert t2_final.rulings["L2"].verdict == "CONDITIONAL"

    sync = ds_issue9.parse_comments(_chain())
    note = ds_issue9.build_heartbeat_note(sync, [], utc="t0", next_wake="t1")
    payload = sync.to_dict()
    assert "can_start_clock" not in payload
    assert "can_start_clock" not in note
    assert "L2-2 START" not in note
    assert sync.rulings["L2"].verdict == "ACCEPTED"


def test_classify_entry_does_not_treat_a_failed_read_as_no_card():
    sync = ds_issue9.parse_comments(
        [_comment(T3_CARD, cid=6775337980, created_at="2026-11-10T18:11:16Z")]
    )
    comment_only = ds_issue9.classify_entry("DS-T3-20261111", False, sync)
    assert comment_only["state"] == "issue_comment_only"
    assert comment_only["in_inbox"] is False
    assert comment_only["comment_id"] == 6775337980

    inbox_hit = ds_issue9.classify_entry("DS-T1-20261108", True, sync)
    assert inbox_hit["state"] == "inbox"
    assert inbox_hit["in_issue_comment"] is False

    absent = ds_issue9.classify_entry("DS-T9-20261112", False, sync)
    assert absent["state"] == "absent"

    failed = ds_issue9.issue9_failure("missing_token", "no token")
    unresolved = ds_issue9.classify_entry("DS-T3-20261111", False, failed)
    assert unresolved["state"] == "unresolved"
    assert unresolved["in_issue_comment"] is False
    assert unresolved["issue_sync_ok"] is False
    assert "can_start_clock" not in unresolved


def test_cli_rejects_stale_note_without_printing_it(tmp_path: Path):
    path = tmp_path / "comments.json"
    path.write_text(
        json.dumps([_comment(FORMAL, cid=6799203994, created_at="2026-11-11T14:58:11Z")]),
        encoding="utf-8",
    )
    draft = "heartbeat utc=t status=idle queue=empty note=L1 done L2 pending"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ds_issue9.py"),
            "--comments-file",
            str(path),
            "--inbox",
            str(tmp_path / "empty-inbox"),
            "--note",
            draft,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 3
    assert "L2 pending" not in proc.stdout
    assert "stale_l2_note_after_accepted" in proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert "status_note" not in payload


def test_cli_task_entry_unions_inbox_and_comment_card(tmp_path: Path):
    comments = tmp_path / "comments.json"
    comments.write_text(
        json.dumps(
            [
                _comment(T3_CARD, cid=6775337980, created_at="2026-11-10T18:11:16Z"),
                _comment(FORMAL, cid=6799203994, created_at="2026-11-11T14:58:11Z"),
            ]
        ),
        encoding="utf-8",
    )
    inbox = tmp_path / "task_inbox"
    (inbox / "DS-T1-20261108").mkdir(parents=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ds_issue9.py"),
            "--comments-file",
            str(comments),
            "--inbox",
            str(inbox),
            "--task-entry",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["comment_cards_not_in_inbox"] == ["DS-T3-20261111"]
    ids = {row["task_id"] for row in payload["entries"]}
    assert ids == {"DS-T1-20261108", "DS-T3-20261111"}
    assert "L2=ACCEPTED" in payload["status_note"]
    assert "L2 pending" not in payload["status_note"]
    assert "can_start_clock" not in payload
    assert "can_start_clock=" not in payload["status_note"]
    assert "L2-2 START" not in payload["status_note"]


def test_worker_entry_reports_unresolved_sync_without_a_ruling():
    env = os.environ.copy()
    env["AISTUDIO_OFFLINE_ENTRY"] = "1"
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "worker_run_task.py"), "--task-id", "DS-T3-20261111"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["error"] == "missing_inbox_issue_sync_unresolved"
    assert payload["entry"]["state"] == "unresolved"
    assert payload["issue9_rulings"] == {}
    assert payload["issue9_sync_error"] == "offline_entry"
    assert "issue9_sync_failed" in payload["status_note"]
    assert "L2 pending" not in proc.stdout
    assert "L2=ACCEPTED" not in proc.stdout
    assert "can_start_clock" not in proc.stdout
    assert "L2-2 START" not in proc.stdout
