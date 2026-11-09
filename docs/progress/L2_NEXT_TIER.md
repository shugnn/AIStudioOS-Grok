# L2 — Approach production 7×24 (not claim it)

**L1 (done-ish):** isolated loop, OS trigger, honest metrics, wall-clock 24h D1 PASS, emergency stop.

**L2 goal:** multi-day *bounded* duty-cycle on one host with stall detection and documented recovery — still **non-production**.

## Gate results

| ID | Gate | Status |
|----|------|--------|
| L2-1 | Stall detection tool | **Code PASS** (`stall_watchdog.py`) |
| L2-4 | 1-day logon schtasks | **INCOMPLETE**. 2026-11-09 host capture `LAPTOP-Q14O4JJT` is in `docs/progress/l2_4/host/` (`host_capture_unverified`). WT Application Error 1000 count 0 in 2026-11-03..06. Task Scheduler Operational log disabled (`task_runs=0`). Tool still cannot close the gate. |
| L2-2 | 72h wall soak | Not started |
| L2-3 | Mid-run kill recovery | Not done |
| L2-5/6 | Boot task / power policy | Default **denied** |

This table is the **duty-cycle** L2 from 2026-11-04. It is not the 2026-11-07 product L2 (task split / worker), which the founder marked **not started**.

## L2-4 — done vs still founder-gated (2026-11-09)

**Done**

- `scripts/l2_4_correlate.py` scores a capture. Report status stays `INCOMPLETE`. `causation` stays `not_proven`. `production_7x24` stays `NOT_ACCEPTED`.
- Scaffold fixtures: `tests/fixtures/l2_4/` (synthetic **2026-01-01**).
- Host capture (real, unverified): `docs/progress/l2_4/host/` from `LAPTOP-Q14O4JJT`, window 2026-11-03T00:00:00Z → 2026-11-06T00:00:00Z. `wt_errors=0` (Application Error 1000 is 1× Explorer.EXE). Six reboot-class events; `reboot_residue.detected=false`. `wake_count=133` from runner files only.
- `scripts/l2_4_capture_host.ps1` stays read-only. Windows PowerShell 5.1 `ToArray()` fix is in-repo. This change does not register tasks.

**Still founder-gated**

1. `Microsoft-Windows-TaskScheduler/Operational` is disabled, so `task_history.available=false` and the blocker stays `scheduler_history_not_in_capture`. Enabling that log is a founder decision, then a read-only re-capture. This change does not enable it.
2. `process_tree.available` is false. Do not type parent/child rows from memory.
3. Do not re-register the 10/15 minute Interactive console tasks until a written host-status note and an explicit re-approval.
4. `can_close_l2_4` remains false. 133 runner wakes are not a scheduler duty PASS.

Commands: `docs/progress/l2_4/README.md`.

## Console note (L2-4 lesson)

Interactive `python.exe` every 10/15 minutes **may** attach default terminal (Windows Terminal). Temporal link to WT Application Error 1000 was strong; causation not process-tree proven. Do not re-enable frequent Interactive console tasks until host stable and founder re-approves.

Production 7×24 remains **NOT ACCEPTED**.
