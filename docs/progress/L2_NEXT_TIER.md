# L2 — Approach production 7×24 (not claim it)

**L1 (done-ish):** isolated loop, OS trigger, honest metrics, wall-clock 24h D1 PASS, emergency stop.

**L2 goal:** multi-day *bounded* duty-cycle on one host with stall detection and documented recovery — still **non-production**.

## Gate results

| ID | Gate | Status |
|----|------|--------|
| L2-1 | Stall detection tool | **Code PASS** (`stall_watchdog.py`) |
| L2-4 | 1-day logon schtasks | **INCOMPLETE** — strong time correlation with Windows Terminal errors; host force-reboot 2026-11-04; tasks left Ready with empty NextRunTime; founder requires console window (no pythonw). 2026-11-09 adds a scaffold correlator + read-only host capture script. Host logs still absent. Tool cannot close the gate. |
| L2-2 | 72h wall soak | Not started |
| L2-3 | Mid-run kill recovery | Not done |
| L2-5/6 | Boot task / power policy | Default **denied** |

This table is the **duty-cycle** L2 from 2026-11-04. It is not the 2026-11-07 product L2 (task split / worker), which the founder marked **not started**.

## L2-4 — done vs still founder-gated (2026-11-09)

**Done (scaffold-verified, not host evidence)**

- `scripts/l2_4_correlate.py` scores a capture: nearest-anchor overlap, Ready+empty `NextRunTime` residue, `pythonw.exe` ban, R7 triage. Report status stays `INCOMPLETE`. `causation` stays `not_proven`. `production_7x24` stays `NOT_ACCEPTED`.
- `docs/progress/l2_4/SCHEMA.json` and `tests/fixtures/l2_4/` (synthetic dates **2026-01-01**).
- `scripts/l2_4_capture_host.ps1` is read-only. It does not register or start tasks. It has not been run here.

**Still founder-gated**

1. Run the capture script on the Windows host for `2026-11-03T00:00:00Z` .. `2026-11-06T00:00:00Z`.
2. Score `docs/progress/l2_4/host/capture.json` and commit capture + report + `SHA256SUMS.json`.
3. Do not invent process-tree rows. The script records `process_tree.available: false`.
4. Do not re-register the 10/15 minute Interactive console tasks until a written host-status note and an explicit re-approval.

Commands: `docs/progress/l2_4/README.md`.

## Console note (L2-4 lesson)

Interactive `python.exe` every 10/15 minutes **may** attach default terminal (Windows Terminal). Temporal link to WT Application Error 1000 was strong; causation not process-tree proven. Do not re-enable frequent Interactive console tasks until host stable and founder re-approves.

Production 7×24 remains **NOT ACCEPTED**.
