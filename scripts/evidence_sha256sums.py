#!/usr/bin/env python3
"""Write SHA256SUMS.json for evidence binding (medium → strong).

Example:
  py -3 scripts/evidence_sha256sums.py docs/progress/soak_2h
  py -3 scripts/evidence_sha256sums.py docs/progress --glob "runner-20261027*.json"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (r.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=str, help="file or directory under repo")
    ap.add_argument("--glob", type=str, default="*", help="when path is dir")
    ap.add_argument(
        "--out",
        type=str,
        default="",
        help="output JSON path (default: <path>/SHA256SUMS.json or sibling)",
    )
    args = ap.parse_args()

    target = Path(args.path)
    if not target.is_absolute():
        target = ROOT / target
    files: list[Path] = []
    if target.is_file():
        files = [target]
        out = Path(args.out) if args.out else target.parent / "SHA256SUMS.json"
    elif target.is_dir():
        files = sorted(p for p in target.glob(args.glob) if p.is_file() and p.name != "SHA256SUMS.json")
        out = Path(args.out) if args.out else target / "SHA256SUMS.json"
    else:
        print(json.dumps({"error": "path_not_found", "path": str(target)}))
        return 1

    if not args.out and not out.is_absolute():
        out = ROOT / out if not str(out).startswith(str(ROOT)) else out

    entries = []
    for p in files:
        rel = str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p)
        entries.append({"path": rel, "sha256": sha256_file(p), "bytes": p.stat().st_size})

    doc = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_sha(),
        "count": len(entries),
        "files": entries,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "count": len(entries), "git_head": doc["git_head"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
