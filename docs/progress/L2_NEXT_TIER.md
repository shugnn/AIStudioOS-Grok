# L2 — Approach production 7×24 (not claim it)

**L1 (done-ish):** isolated loop, OS trigger, honest metrics, wall-clock 24h D1 PASS, emergency stop.

**L2 goal:** multi-day *bounded* duty-cycle on one host with stall detection and documented recovery — still **non-production**.

## Gate results

| ID | Gate | Status |
|----|------|--------|
| L2-1 | Stall detection tool | **Code PASS** (`stall_watchdog.py`) |
| L2-4 | 1-day logon schtasks | **INCOMPLETE**. Operational log is enabled on `LAPTOP-Q14O4JJT`. Re-capture of 2026-11-03..06 still has zero scheduler starts for the watched task names (`task_history.available=true`, `task_runs=0`, no backfill). WT Application Error 1000 count 0. Tool still cannot close the gate. |
| L2-2 | 72h wall soak | Not started |
| L2-3 | Mid-run kill recovery | Not done |
| L2-5/6 | Boot task / power policy | Default **denied** |

This table is the **duty-cycle** L2 from 2026-11-04. It is not the 2026-11-07 product L2 (task split / worker), which the founder marked **not started**.

## L2-4 — done vs still founder-gated (2026-11-09)

**Done**

- `scripts/l2_4_correlate.py` scores a capture. Report status stays `INCOMPLETE`. `causation` stays `not_proven`. `production_7x24` stays `NOT_ACCEPTED`.
- Scaffold fixtures: `tests/fixtures/l2_4/` (synthetic **2026-01-01**).
- Host re-capture (real, unverified): `docs/progress/l2_4/host/` from `LAPTOP-Q14O4JJT`, same window. Operational log is enabled. `task_history.available=true`, `task_runs=0` (empty is a real zero; the log was off during the window and does not backfill). `wt_errors=0` (1× Explorer.EXE). Six reboot-class events; `reboot_residue.detected=false`. `correlation.basis=task_runs`, `strength=no_events`, `wake_count=0`.
- `scripts/l2_4_capture_host.ps1` stays read-only. PS 5.1 `ToArray()` plus zh-CN empty-result match (`找不到任何与指定的选择条件匹配的事件`). This change does not register tasks.

**Still founder-gated**

1. `scheduler_history_not_in_capture` is removed. Blockers are now `tool_does_not_close_gate`, `time_correlation_is_not_causation`, `founder_reapproval_required_before_new_interactive_duty`, `process_tree_unavailable`, `no_duty_anchors`, `fewer_than_20_duty_wakes`.
2. 11/04 Windows Terminal / reboot causation cannot be reconstructed from scheduler history.
3. A forward-looking soak with history already on is a separate founder gate. Do not re-enable the 10/15 minute Interactive console tasks.
4. `process_tree.available` is false. Do not type parent/child rows from memory. `can_close_l2_4` remains false.

Commands: `docs/progress/l2_4/README.md`.

## Console note (L2-4 lesson)

Interactive `python.exe` every 10/15 minutes **may** attach default terminal (Windows Terminal). Temporal link to WT Application Error 1000 was strong; causation not process-tree proven. Do not re-enable frequent Interactive console tasks until host stable and founder re-approves.

Production 7×24 remains **NOT ACCEPTED**.
