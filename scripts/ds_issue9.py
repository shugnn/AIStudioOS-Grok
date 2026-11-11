#!/usr/bin/env python3
"""Sync official 观察轨 (DS) rulings and task cards from Issue #9 comments.

Heartbeat, status-line, and task-entry checks in this repo must call this
module before they emit a note. ``task_inbox/`` stays a valid input and is
not the only one.

What this module does not do:

- It does not post GitHub comments.
- It does not start the L2-2 72h clock, write an ``L2-2 START`` registration,
  launch a soak, or set ``can_start_clock``.
- It does not claim production 7×24 is accepted. That boundary is fixed here
  as ``NOT_ACCEPTED``; this helper cannot grant it.
- It does not, by itself, stop grok.com / the ``grok-by-xai`` GitHub App from
  posting stale heartbeat notes. Those notes stop only if that side calls
  this helper before it writes.
- A missing token or a GitHub API failure yields an empty ruling set and an
  error code. It never fills in ACCEPTED, CONDITIONAL, or REJECTED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "shugnn/AIStudioOS-Grok"
ISSUE_NUMBER = 9
VERDICTS = ("ACCEPTED", "CONDITIONAL", "REJECTED")
DS_SIGNATURE = "观察轨（DS）代发"
PRODUCTION_7X24 = "NOT_ACCEPTED"
SCOPE = (
    "Repo-side Issue #9 sync for heartbeat, status, and task entry. "
    "Does not post comments, does not start the L2-2 clock, does not set "
    "can_start_clock, does not claim production 7x24 accepted, and does not "
    "by itself stop grok.com / grok-by-xai from posting stale notes."
)

_ITEM_ORDER = ("T1", "T2", "T3", "T4", "T5", "L1", "L2", "L3", "L4")
_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?P<item>L[1-4]|T[1-9])(?!-\d)"
    r"(?:（[^）\n]{0,80}）)?"
    r"(?:\s*判定)?"
    r"(?:\s*=\s*|\s*仍\s*|\s*[:：]\s*)"
    r"(?P<verdict>CONDITIONAL(?:\s+ACCEPTED)?|ACCEPTED|REJECTED)\b",
    re.IGNORECASE,
)
_HEADER_VERDICT_RE = re.compile(
    r"【(?P<item>L[1-4]|T[1-9])(?!-\d)[^】]{0,80}】"
    r"[^\n]{0,160}?"
    r"(?P<verdict>CONDITIONAL(?:\s+ACCEPTED)?|ACCEPTED|REJECTED)\b",
    re.IGNORECASE,
)
_TASK_CARD_RE = re.compile(
    r"【正式任务卡(?P<title>[^】]*)】[\s\S]{0,500}?"
    r"TASK\s*ID\s*[：:]\s*\*{0,2}`?(?P<tid>DS-T\d+-\d{8})`?",
    re.IGNORECASE,
)
_STALE_L2_RE = re.compile(
    r"L2\s*pending"
    r"|L2\s*not[\s_-]*started"
    r"|L2\s*not[\s_-]*start\b"
    r"|L2\s*idle\b"
    r"|L2\s*未开始"
    r"|L2\s*未启动"
    r"|L2notstart"
    r"|L2未开始",
    re.IGNORECASE,
)
_NO_TASK_RE = re.compile(
    r"queue\s*=\s*empty|no[\s_-]*new[\s_-]*tasks?|无新任务",
    re.IGNORECASE,
)
_WORKER_PREFIXES = (
    "heartbeat ",
    "heartbeat\t",
    "status_line ",
    "status_line\t",
    "[worker]",
    "【worker",
    "l2-2 worker",
    "## ack",
    "## 日间",
    "ack ",
)


class StaleNoteError(Exception):
    """A draft note contradicts Issue #9 or was not grounded in a sync."""

    def __init__(self, reason: str, note: str):
        super().__init__(reason)
        self.reason = reason
        self.note = note


class _SyncFailure(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class Ruling:
    item: str
    verdict: str
    comment_id: int | None
    created_at: str
    excerpt: str


@dataclass
class TaskCard:
    task_id: str
    comment_id: int | None
    created_at: str
    title: str


@dataclass
class Issue9Sync:
    ok: bool
    error_code: str | None
    error_detail: str | None
    rulings: dict[str, Ruling] = field(default_factory=dict)
    task_cards: list[TaskCard] = field(default_factory=list)
    comments_seen: int = 0
    official_comments_seen: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "rulings": {key: asdict(value) for key, value in self.rulings.items()},
            "task_cards": [asdict(card) for card in self.task_cards],
            "comments_seen": self.comments_seen,
            "official_comments_seen": self.official_comments_seen,
            "production_7x24": PRODUCTION_7X24,
            "scope": SCOPE,
        }


def issue9_failure(code: str, detail: str) -> Issue9Sync:
    return Issue9Sync(ok=False, error_code=code, error_detail=detail)


def _comment_id(comment: dict) -> int | None:
    raw = comment.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _excerpt(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    if end < 0:
        end = len(text)
    line = " ".join(text[start:end].split())
    return line[:180]


def normalize_verdict(raw: str) -> str:
    verdict = re.sub(r"\s+", " ", raw.strip().upper())
    if verdict.startswith("CONDITIONAL"):
        return "CONDITIONAL"
    if verdict == "ACCEPTED":
        return "ACCEPTED"
    if verdict == "REJECTED":
        return "REJECTED"
    raise ValueError(raw)


def is_official_ds_comment(body: str) -> bool:
    """True for 观察轨 posts, not for worker echoes of the same words.

    The GitHub login is not a discriminator: DS rulings and Grok-track notes
    are both posted by the repository owner. The signature line is.
    """
    text = (body or "").lstrip("\ufeff").strip()
    if DS_SIGNATURE not in text:
        return False
    first = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            first = stripped
            break
    lowered = first.lower()
    return not lowered.startswith(_WORKER_PREFIXES)


def extract_rulings(body: str) -> list[tuple[str, str, str]]:
    """Return (item, verdict, excerpt) in document order.

    ``CONDITIONAL ACCEPTED`` is CONDITIONAL. ``NOT ACCEPTED`` and
    ``NOT STARTED`` are not triad rulings. A later hypothetical such as
    "作废并按 REJECTED 处理" is not a ruling unless an item is assigned.
    ``L2-2`` is not product L2.
    """
    text = (body or "").lstrip("\ufeff")
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for match in _ASSIGN_RE.finditer(text):
        item = match.group("item").upper()
        verdict = normalize_verdict(match.group("verdict"))
        found.append((item, verdict, _excerpt(text, match.start())))
        seen.add(item)
    for line in text.splitlines():
        match = _HEADER_VERDICT_RE.search(line)
        if not match:
            continue
        item = match.group("item").upper()
        if item in seen:
            continue
        verdict = normalize_verdict(match.group("verdict"))
        found.append((item, verdict, _excerpt(line, match.start())))
        seen.add(item)
    return found


def extract_task_cards(body: str) -> list[tuple[str, str]]:
    text = (body or "").lstrip("\ufeff")
    cards: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _TASK_CARD_RE.finditer(text):
        task_id = match.group("tid")
        if task_id in seen:
            continue
        seen.add(task_id)
        title = " ".join((match.group("title") or "").split())
        cards.append((task_id, title))
    return cards


def parse_comments(comments: list[dict]) -> Issue9Sync:
    """Latest official triad ruling wins per item. Earliest task card is kept."""
    ordered = sorted(
        comments or [],
        key=lambda comment: (str(comment.get("created_at") or ""), _comment_id(comment) or 0),
    )
    rulings: dict[str, Ruling] = {}
    cards: list[TaskCard] = []
    seen_cards: set[str] = set()
    official = 0
    for comment in ordered:
        body = comment.get("body") or ""
        if not is_official_ds_comment(body):
            continue
        official += 1
        comment_id = _comment_id(comment)
        created_at = str(comment.get("created_at") or "")
        for item, verdict, excerpt in extract_rulings(body):
            rulings[item] = Ruling(
                item=item,
                verdict=verdict,
                comment_id=comment_id,
                created_at=created_at,
                excerpt=excerpt,
            )
        for task_id, title in extract_task_cards(body):
            if task_id in seen_cards:
                continue
            seen_cards.add(task_id)
            cards.append(
                TaskCard(
                    task_id=task_id,
                    comment_id=comment_id,
                    created_at=created_at,
                    title=title,
                )
            )
    return Issue9Sync(
        ok=True,
        error_code=None,
        error_detail=None,
        rulings=rulings,
        task_cards=cards,
        comments_seen=len(comments or []),
        official_comments_seen=official,
    )


def fetch_comments(
    token: str,
    *,
    opener=None,
    repo: str = REPO,
    issue: int = ISSUE_NUMBER,
    timeout: int = 30,
) -> list[dict]:
    """Read every Issue comment page. Any page failure fails the whole read.

    A partial list is not returned: a later page can hold the ruling that
    makes an earlier note stale.
    """
    if not token or not str(token).strip():
        raise _SyncFailure(
            "missing_token",
            "GH_TOKEN or GITHUB_TOKEN is required to read Issue comments; no ruling invented",
        )
    open_fn = opener or urllib.request.urlopen
    collected: list[dict] = []
    page = 1
    while page <= 30:
        url = (
            f"https://api.github.com/repos/{repo}/issues/{issue}/comments"
            f"?per_page=100&page={page}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "AIStudioOS-Grok-DS-Issue9",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with open_fn(req, timeout=timeout) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            raise _SyncFailure(
                "api_failure",
                f"HTTP {exc.code} reading {repo} issue #{issue} comments",
            ) from exc
        except urllib.error.URLError as exc:
            raise _SyncFailure("api_failure", f"URLError: {exc.reason}") from exc
        except Exception as exc:
            raise _SyncFailure("api_failure", f"{type(exc).__name__}: {exc}") from exc
        try:
            batch = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _SyncFailure("api_failure", f"comments response was not JSON: {exc}") from exc
        if not isinstance(batch, list):
            raise _SyncFailure("api_failure", "comments response was not a JSON list")
        collected.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return collected


def sync_issue9(
    token: str | None,
    *,
    comments: list[dict] | None = None,
    opener=None,
    repo: str = REPO,
    issue: int = ISSUE_NUMBER,
) -> Issue9Sync:
    """Sync from injected comments, or from the GitHub API.

    Injected comments are a completed read (tests and replay). They are not
    used by the heartbeat, status-line, or task-entry scripts.
    """
    if comments is not None:
        return parse_comments(comments)
    if not token or not str(token).strip():
        return issue9_failure(
            "missing_token",
            "GH_TOKEN or GITHUB_TOKEN is required to read Issue comments; no ruling invented",
        )
    try:
        fetched = fetch_comments(token, opener=opener, repo=repo, issue=issue)
    except _SyncFailure as exc:
        return issue9_failure(exc.code, exc.detail)
    return parse_comments(fetched)


def inbox_task_ids(inbox: Path) -> list[str]:
    if not inbox.is_dir():
        return []
    return sorted(
        path.name
        for path in inbox.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )


def new_task_cards(sync: Issue9Sync, inbox_ids: list[str] | tuple[str, ...]) -> list[TaskCard]:
    if not sync.ok:
        return []
    present = set(inbox_ids)
    return [card for card in sync.task_cards if card.task_id not in present]


def task_entries(sync: Issue9Sync, inbox_ids: list[str] | tuple[str, ...]) -> list[dict]:
    """Union of inbox folders and official comment cards. Inbox is not exclusive."""
    rows: dict[str, dict] = {}
    for task_id in inbox_ids:
        rows[task_id] = {
            "task_id": task_id,
            "in_inbox": True,
            "in_issue_comment": False,
            "comment_id": None,
            "created_at": None,
        }
    if sync.ok:
        for card in sync.task_cards:
            row = rows.get(card.task_id)
            if row is None:
                rows[card.task_id] = {
                    "task_id": card.task_id,
                    "in_inbox": False,
                    "in_issue_comment": True,
                    "comment_id": card.comment_id,
                    "created_at": card.created_at,
                }
            else:
                row["in_issue_comment"] = True
                row["comment_id"] = card.comment_id
                row["created_at"] = card.created_at
    return [rows[key] for key in sorted(rows)]


def classify_entry(task_id: str, inbox_present: bool, sync: Issue9Sync) -> dict:
    """Locate one task without treating a failed comment read as 'no card'."""
    card = None
    if sync.ok:
        for candidate in sync.task_cards:
            if candidate.task_id == task_id:
                card = candidate
                break
        if inbox_present:
            state = "inbox"
        elif card is not None:
            state = "issue_comment_only"
        else:
            state = "absent"
    else:
        state = "inbox_unverified_comments" if inbox_present else "unresolved"
    return {
        "task_id": task_id,
        "state": state,
        "in_inbox": bool(inbox_present),
        "in_issue_comment": card is not None,
        "comment_id": None if card is None else card.comment_id,
        "created_at": None if card is None else card.created_at,
        "issue_sync_ok": sync.ok,
        "issue_sync_error": sync.error_code,
    }


def prepare_note(note: str, sync: Issue9Sync, inbox_ids: list[str] | tuple[str, ...] = ()) -> str:
    """Return ``note`` if it may be emitted. Raise ``StaleNoteError`` otherwise.

    Callers must not write ``exc.note`` into a heartbeat, status line, or
    task-entry status when this raises.
    """
    text = "" if note is None else str(note)
    if not text.strip():
        raise StaleNoteError("empty_note", text)
    if "can_start_clock" in text.lower() or re.search(r"L2-2\s+START\s*:", text, re.IGNORECASE):
        raise StaleNoteError("refusing_l2_2_start_or_clock_flag", text)
    if re.search(r"production_7x24\s*=\s*ACCEPTED\b", text, re.IGNORECASE):
        raise StaleNoteError("refusing_production_7x24_accepted", text)
    if not sync.ok:
        if _ASSIGN_RE.search(text):
            raise StaleNoteError("sync_failed_would_invent_ruling", text)
        if _STALE_L2_RE.search(text):
            raise StaleNoteError("sync_failed_refusing_unverified_l2_status", text)
        if _NO_TASK_RE.search(text):
            raise StaleNoteError("sync_failed_refusing_queue_claim", text)
        return text
    ruling = sync.rulings.get("L2")
    if ruling is not None and ruling.verdict in VERDICTS and _STALE_L2_RE.search(text):
        raise StaleNoteError(f"stale_l2_note_after_{ruling.verdict.lower()}", text)
    if new_task_cards(sync, inbox_ids) and _NO_TASK_RE.search(text):
        raise StaleNoteError("queue_empty_while_issue_task_card", text)
    claimed: dict[str, str] = {}
    for match in _ASSIGN_RE.finditer(text):
        claimed[match.group("item").upper()] = normalize_verdict(match.group("verdict"))
    for item, held in sync.rulings.items():
        if claimed.get(item) != held.verdict:
            raise StaleNoteError(
                f"note_does_not_reflect_{item.lower()}_{held.verdict.lower()}",
                text,
            )
    for item, verdict in claimed.items():
        held = sync.rulings.get(item)
        if held is None or held.verdict != verdict:
            raise StaleNoteError(f"ungrounded_{item.lower()}_ruling", text)
    return text


def _ruling_note_parts(sync: Issue9Sync) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    for item in _ITEM_ORDER:
        ruling = sync.rulings.get(item)
        if ruling is None:
            continue
        parts.append(f"{item}={ruling.verdict}")
        seen.add(item)
    for item in sorted(sync.rulings):
        if item in seen:
            continue
        parts.append(f"{item}={sync.rulings[item].verdict}")
    if not parts:
        parts.append("no_ds_ruling")
    return parts


def build_heartbeat_note(
    sync: Issue9Sync,
    inbox_ids: list[str] | tuple[str, ...],
    *,
    utc: str,
    next_wake: str,
) -> str:
    """One heartbeat line grounded in a sync. Refuses its own output if stale."""
    if not sync.ok:
        note = (
            f"heartbeat utc={utc} next_wake_utc={next_wake} status=unknown queue=unknown "
            f"note=issue9_sync_failed error={sync.error_code} "
            f"production_7x24={PRODUCTION_7X24}"
        )
        return prepare_note(note, sync, inbox_ids)
    parts = _ruling_note_parts(sync)
    missing = new_task_cards(sync, inbox_ids)
    if missing:
        status = "work"
        queue = "has_task"
        parts.append("new_task_cards=" + ",".join(card.task_id for card in missing))
    elif inbox_ids:
        status = "idle"
        queue = "has_task"
    else:
        status = "idle"
        queue = "empty"
    note = (
        f"heartbeat utc={utc} next_wake_utc={next_wake} status={status} queue={queue} "
        f"note={' '.join(parts)} production_7x24={PRODUCTION_7X24}"
    )
    return prepare_note(note, sync, inbox_ids)


def build_status_line(
    sync: Issue9Sync,
    inbox_ids: list[str] | tuple[str, ...],
    *,
    utc: str,
    next_wake: str,
) -> str:
    heartbeat = build_heartbeat_note(sync, inbox_ids, utc=utc, next_wake=next_wake)
    if heartbeat.startswith("heartbeat "):
        return "status_line " + heartbeat[len("heartbeat ") :]
    return heartbeat


def _load_comments_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("comments"), list):
        data = data["comments"]
    if not isinstance(data, list):
        raise SystemExit("comments file must be a JSON list")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync DS rulings and task cards from Issue #9")
    parser.add_argument("--note", help="Gate a draft note. A refused note is not printed as status.")
    parser.add_argument("--status-line", action="store_true", help="Print one gated status line")
    parser.add_argument("--task-entry", action="store_true", help="Print inbox ∪ Issue #9 task cards")
    parser.add_argument(
        "--comments-file",
        help="Replay a JSON comment list. Heartbeat/status/task-entry scripts do not use this.",
    )
    parser.add_argument("--inbox", default=str(ROOT / "task_inbox"))
    args = parser.parse_args(argv)

    inbox_ids = inbox_task_ids(Path(args.inbox))
    if args.comments_file:
        sync = parse_comments(_load_comments_file(Path(args.comments_file)))
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        sync = sync_issue9(token)

    if args.note:
        try:
            prepare_note(args.note, sync, inbox_ids)
        except StaleNoteError as exc:
            print(json.dumps({"ok": False, "error": "stale_note", "reason": exc.reason}, ensure_ascii=False))
            return 3
        print(json.dumps({"ok": True, "reason": "note_allowed"}, ensure_ascii=False))
        return 0

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    utc = now.isoformat()
    next_wake = (now + timedelta(hours=1)).isoformat()
    try:
        status_note = build_status_line(sync, inbox_ids, utc=utc, next_wake=next_wake)
    except StaleNoteError as exc:
        print(json.dumps({"ok": False, "error": "stale_note", "reason": exc.reason}, ensure_ascii=False))
        return 3

    if args.status_line:
        print(status_note)
    elif args.task_entry:
        missing = None if not sync.ok else [card.task_id for card in new_task_cards(sync, inbox_ids)]
        print(
            json.dumps(
                {
                    "ok": sync.ok,
                    "error_code": sync.error_code,
                    "error_detail": sync.error_detail,
                    "rulings": {key: asdict(value) for key, value in sync.rulings.items()},
                    "task_cards": [asdict(card) for card in sync.task_cards],
                    "entries": task_entries(sync, inbox_ids),
                    "comment_cards_not_in_inbox": missing,
                    "status_note": status_note,
                    "production_7x24": PRODUCTION_7X24,
                    "scope": SCOPE,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        payload = sync.to_dict()
        payload["entries"] = task_entries(sync, inbox_ids)
        payload["status_note"] = status_note
        payload["comment_cards_not_in_inbox"] = (
            None if not sync.ok else [card.task_id for card in new_task_cards(sync, inbox_ids)]
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if not sync.ok:
        return 2 if sync.error_code == "missing_token" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
