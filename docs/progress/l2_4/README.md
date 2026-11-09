# L2-4 — WT correlation + reboot (still INCOMPLETE)

Duty-cycle gate from `L2_NEXT_TIER.md`. This is **not** the 2026-11-07 product L2 (task split / worker), which stays **not started**.

Production 7×24: **NOT ACCEPTED**. L2-4: **INCOMPLETE**.

The 2026-11-04 incident narrative (Interactive `python.exe`, a Windows Terminal time association, tasks left Ready with an empty `NextRunTime`) is unchanged. The current host export in `docs/progress/l2_4/host/` is the second read-only capture from `LAPTOP-Q14O4JJT` after `Microsoft-Windows-TaskScheduler/Operational` was enabled. The 2026-11-03..06 window still has zero scheduler starts for the watched task names. WT Application Error 1000 count is 0. L2-4 stays **INCOMPLETE**.

## Done in repo (scaffold-verified)

| Piece | What it is |
|-------|------------|
| `scripts/l2_4_correlate.py` | Offline scorer. Emits `INCOMPLETE`, `causation=not_proven`, `production_7x24=NOT_ACCEPTED`. Refuses `PASS`. |
| `docs/progress/l2_4/SCHEMA.json` | Capture/report ids, strength rule, reboot event ids |
| `tests/fixtures/l2_4/` | Synthetic captures dated **2026-01-01**. Not host evidence. |
| `tests/test_l2_4_correlate.py` | Strength bands, residue, pythonw, history-vs-runner, forged-PASS rejection |
| `scripts/l2_4_capture_host.ps1` | Read-only Windows collector. PS 5.1 uses `.ToArray()` inside the `[ordered]` capture literal. |
| `docs/progress/l2_4/host/` | Real `host_capture` from `LAPTOP-Q14O4JJT`. Label on the report: `host_capture_unverified`. Still **INCOMPLETE**. |

Reproduce the scaffold (any OS with Python 3):

```bash
PYTHONPATH=. python -m pytest tests/test_l2_4_correlate.py -q
PYTHONPATH=. python scripts/l2_4_correlate.py \
  --capture tests/fixtures/l2_4/scaffold_strong_time_overlap.json
```

Exit 0 means the report is an honest INCOMPLETE document. It does **not** mean L2-4 passed.

## Still founder-gated

The second export is in-repo and stays unverified. History is readable and empty for that window; enabling the log did not backfill it. Next options: a forward-looking soak with history already on (separate founder gate), or accept that 11/04 Windows Terminal / reboot causation cannot be reconstructed from scheduler history. Do **not** register or start `AIStudioOS-Grok-L1` / `AIStudioOS-Grok-Watchdog`. Do not treat runner files as scheduler wakes (`wake_count=0` on `task_runs`).

```powershell
cd <repo>
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\l2_4_capture_host.ps1 `
  -OutDir .\docs\progress\l2_4\host `
  -Since "2026-11-03T00:00:00Z" `
  -Until "2026-11-06T00:00:00Z"
py -3 scripts\l2_4_correlate.py `
  --capture docs\progress\l2_4\host\capture.json `
  --out docs\progress\l2_4\host\report.json
py -3 scripts\evidence_sha256sums.py docs\progress\l2_4\host
```

What the capture must contain before anyone treats it as host evidence:

| Check | Pass condition for *collection* (still not L2-4 PASS) |
|-------|--------------------------------------------------------|
| `evidence_class` | `host_capture` and `synthetic` false |
| Tasks | `Get-ScheduledTask` + `Get-ScheduledTaskInfo` for both names, or an explicit `present: false` if already removed |
| Residue | `state`, `next_run_time`, `last_run_time` copied, not retyped |
| WT | Application log, provider `Application Error`, id **1000**, faulting app `WindowsTerminal.exe` or `wt.exe` |
| Reboot | System events **1074, 6008, 41, 6005, 6006, 12** inside the window |
| Scheduler starts | `Microsoft-Windows-TaskScheduler/Operational` id **200**. If that log is disabled, `task_history.available` must be false — do not fill fake start times |
| Process tree | This script leaves `process_tree.available` false. Do not type parent/child rows from memory |
| Console | `execute` must not be `pythonw.exe` |

Optional, separate from capture, only if the founder wants the old tasks gone:

```powershell
Unregister-ScheduledTask -TaskName "AIStudioOS-Grok-L1" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "AIStudioOS-Grok-Watchdog" -Confirm:$false -ErrorAction SilentlyContinue
```

Do not re-enable a 10/15 minute Interactive console task until the host-status note is written and the founder explicitly re-approves. L2-5/L2-6 stay denied.

## What a future close would still require

This correlator will keep `can_close_l2_4: false`. Closing the gate needs a **new** founder-approved run, then observation-track review. Twenty wakes plus a strong time overlap is not a close: the unit test `test_twenty_scheduler_wakes_do_not_close_gate` locks that.
