# Issue #9 comment sync

`scripts/ds_issue9.py` reads GitHub Issue #9 comments on `shugnn/AIStudioOS-Grok` before a Grok-track heartbeat, status line, or task-entry check emits a note.

It extracts:

- the latest official 观察轨 (DS) ruling among `ACCEPTED`, `CONDITIONAL`, and `REJECTED` for items such as T3 and product L2 (latest comment wins per item; `CONDITIONAL ACCEPTED` counts as `CONDITIONAL`)
- whether an official DS task card (`【正式任务卡】` plus `TASK ID`) was published in those comments

`scripts/l1_heartbeat.py`, `scripts/status_line.py`, `scripts/task_entry.py`, and the entry check in `scripts/worker_run_task.py` call it first. A draft that still says `L2 pending` or `L2 not started` after an L2 ruling is refused and is not written as the note. `task_inbox/` remains a valid input. A card that exists only in an Issue comment is still a task entry.

A missing token or a GitHub API failure is `missing_token` or `api_failure`, with an empty ruling list. The helper does not invent a verdict. A failed page does not keep earlier pages: the later page may be the one that changed the ruling.

## What this does not do

- It does not post Issue comments.
- It does not start the L2-2 72h clock, write an `L2-2 START` registration, launch a soak, or set `can_start_clock`.
- It does not claim production 7×24 is accepted. Notes keep `production_7x24=NOT_ACCEPTED` as a fixed boundary of this helper, not as a grant it can flip.
- It does not, by itself, stop grok.com / the GitHub App `grok-by-xai` from posting stale `heartbeat` or `status_line` comments. Those notes change only if that side starts using this helper before it writes.
