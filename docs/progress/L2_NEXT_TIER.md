# L2 — Approach production 7×24 (not claim it)

**L1 (done-ish):** isolated loop, OS trigger, honest metrics, wall-clock 24h D1 PASS, emergency stop.

**L2 goal:** multi-day *bounded* duty-cycle on one host with stall detection and documented recovery — still **non-production**.

## Gate results

| ID | Gate | Status |
|----|------|--------|
| L2-1 | Stall detection tool | **Code PASS** (`stall_watchdog.py`) |
| L2-4 | 1-day logon schtasks | **INCOMPLETE** — strong time correlation with Windows Terminal errors; host force-reboot 2026-11-04; tasks left Ready with empty NextRunTime; founder requires console window (no pythonw) |
| L2-2 | 72h wall soak | **NOT STARTED** — scaffold only (`docs/progress/l2_2/`), including `scripts/health_check.py`, the offline stall-watchdog hook, the Ubuntu-24H historical SHORT specimen binding, a non-additivity gate (ended 24h walls do not sum to 72h), a process-boundary continuity gate (sequential or restarted soaks do not stitch into 72h), a founder-start honesty gate, an offline supervisor-watchdog honesty gate (synthetic files only; not founder condition 2; not a start), and blank `START_DECISION.md`. Clock not started. **NOT ACCEPTED**. No Interactive schtasks |
| L2-3 | Mid-run kill recovery | Not done |
| L2-5/6 | Boot task / power policy | Default **denied** |

This table is the **duty-cycle** L2. It is not the 2026-11-07 product L2 (self-decompose / self-implement). On Issue #9, T2 (`DS-T2-20261110`) is **ACCEPTED** (comment 6765608469, 2026-11-10T11:00:40Z, evidence PR #13 tip `9cac002`). Product L2 is **CONDITIONAL**, not granted: comment 6767990189 (2026-11-10T13:00:44Z) accepted PR #14 tip `738b47a` as evidence that a different goal and schema yields a different task set, and left one end-to-end pending (new goal, new schema, the product derives then executes and delivers, no handwritten dispatch). The observation track said that end-to-end will be T3. No `task_inbox/DS-T3-*` card is on main. PR #15 tip `a07ec9f` prepared that path and is not a T3 run and not acceptance.

## L2-2 — scaffold vs a real 72h

**In repo**

- `scripts/l2_2_score.py` scores a bundle. Status stays `NOT_STARTED` or `INCOMPLETE`. `production_7x24` stays `NOT_ACCEPTED`. `can_accept_l2_2`, `can_close_l2_2`, and `can_start_clock` stay false.
- 72h means monotonic `wall_elapsed_s` ≥ **259200** with `max_wall_seconds` 259200, driven by existing `scripts/soak_2h.py --via-l1`. `cycles × interval` is not the wall. `cycles_exit0` is not business progress.
- Scaffold fixtures: `tests/fixtures/l2_2/` (synthetic **2026-02-01**). Not the 2026-11-03..06 incident and not Ubuntu-24H.
- The scorer does not register scheduled tasks and does not start a clock.
- `scripts/coverage_gap_log.py` appends ok/yellow/red gap lines. `docs/progress/l2_2/R2_CHECKLIST.md` is the blank R2 note. Neither one starts the 72h clock.
- `scripts/l2_2_preflight.py` checks that scaffold offline. Exit 0 is a `NOT_STARTED` report. `can_start_clock` stays false. Running it is not a start decision and does not launch the soak.
- The same preflight runs `scripts/stall_watchdog.py` as an offline hook: a synthetic fresh summary is not stalled, a synthetic stale summary is stalled. Bands come from `scripts/coverage_gap_log.py` and are not appended. The hook does not watch the Ubuntu-24H files under `docs/progress/soak_2h` (wall 86400.001s, **SHORT**), does not write `docs/progress/STALL_ALERT.json`, and does not start the 72h clock. L2-1 code PASS is not a 72h PASS.
- The same preflight reads `docs/progress/soak_2h/metrics.json` as a historical SHORT specimen (wall 86400.001s, below 259200). `ubuntu_24h_counts_as_72h` and `ubuntu_24h_used_as_dut` stay false. Overall `l2_2_status` / `clock_state` stay `NOT_STARTED`. That binding is not a start and is not the 72h gate.
- Ended SHORT walls are not additive. 72h is one continuous monotonic wall on a single live soak. A sum of 24h walls, including 86400.001 plus another 86400 and 86400 times 3, does not count toward 259200. That gate is not a start. No Windows D1 metrics file is committed here, so none is bound.
- Sequential or restarted soak invocations are not one live process. A back-to-back pair of 86400s soaks, three sequential 86400s soaks covering 72h of calendar time, or a wall that resets, does not count toward 259200 even on the same host. `sequential_soaks_are_continuous` and `stitched_processes_count_toward_gate` stay false. That continuity gate is not a start. The clock stays **NOT STARTED**.
- The same preflight classifies synthetic supervisor-alive and supervisor-crash-unrecorded temp files. That offline probe does not satisfy founder condition 2 (a supervision write at least once every 10 minutes, and another process recording a supervisor crash within 10 seconds). It is not a watchdog of a live supervisor, and `scripts/stall_watchdog.py` is not that watchdog either. The probe is not a start.
- `scripts/health_check.py` re-runs that preflight and scores the not-started fixture. Exit 0 is `overall_ok`. It is not a start and not acceptance.
- `docs/progress/l2_2/START_DECISION.md` is the blank start-decision template (decision **Not given**, who / UTC time / host unfilled). Filling or committing that file does not start the soak. Interactive console scheduled tasks stay founder-gated and out of scope.
- `docs/progress/l2_2/SHA256SUMS.json` (from `scripts/evidence_sha256sums.py`) binds the scaffold bytes. The binding does not start the clock and does not accept production 7×24.

**Still required before any real clock**

1. An explicit founder or worker decision to start the existing non-Interactive local soak. This scaffold is not that decision.
2. An R2 note written before the process starts (live soak summary, or live `runner-*.json` only when no soak is the DUT).
3. Do **not** register, create, or enable Interactive console scheduled tasks. That remains a founder major gate and is not approved here.

L2-4 stays **INCOMPLETE**. Historical reconstruction is exhausted on PR #11 (tip `931758c`): Operational history is on, and 2026-11-03..06 still has `task_runs=0` and WT Error 1000 count 0. Do not re-capture that window to start L2-2.

Commands and the later start line: `docs/progress/l2_2/README.md`.

## Console note (L2-4 lesson)

Interactive `python.exe` every 10/15 minutes **may** attach default terminal (Windows Terminal). Temporal link to WT Application Error 1000 was strong; causation not process-tree proven. Do not re-enable frequent Interactive console tasks until host stable and founder re-approves.

Production 7×24 remains **NOT ACCEPTED**.
