# Grok track — Supervision strategy declaration (FOUNDER R1–R8)

**Effective:** FOUNDER instruction 2026-11-05 · supervision layer is an acceptance object.
**Track:** AIStudioOS-Grok · P0 Issue #9  
**Boundary:** $0 · no ChatGPT repo edits · no production 7×24 claim

## R2 — Strategy for the *next* long run (must be posted before start)

| Item | Grok default |
|------|----------------|
| Heartbeat / progress signal | Prefer **L1** `docs/progress/runner-*.json` mtime (or soak `summary.jsonl` when soak is the DUT) |
| Watch period | Check every **60–180 s** in a dedicated monitor process *or* document schtasks interval |
| **Yellow** | Signal gap **13 s – 5 min**: log `coverage_gap`, **do not** FAIL the business run |
| **Red** | Signal gap **> 5 min**: stop DUT if still owned by this monitor, seal metrics, attribute **supervision failure** (unless pre-declared tighter policy with proof) |
| On yellow | Continue; append one `scripts/coverage_gap_log.py` record (`timestamp`, `gap_seconds`, `band=yellow`, `source`, monotonic `mono_seconds`). Yellow is not a business FAIL |
| On red | Stop + seal; report under R7 as supervision failure |
| Who decides business vs supervision | **Business:** task ACCEPTED/exit metrics, with_work counts. **Supervision:** missing/late progress signals, monitor crash, wrong watch target. **Host:** reboot, OOM, shell crash, power |

### Explicit ban (L2-4 lesson)

- Do **not** point the watchdog at an **ended** experiment’s file (e.g. old soak `summary.jsonl` while only L1 runs).
- Use `--runner-glob` when DUT is L1 schtasks duty.
- Trigger count ≠ effective output (R5).

## R3 — Supervision drop injection (required before long-run PASS counts as verified)

| Step | Action | Expected |
|------|--------|----------|
| Y | Pause monitor **30 s** (or block signal path 30 s) | DUT continues; `coverage_gap` recorded; **not** business FAIL |
| R | Pause monitor **6 min** | Stop/seal; attribute **supervision failure** |

Receipt: JSON under `docs/progress/supervision_injection/` with timestamps (timezone + monotonic), outcomes, git SHA.

**Status:** tooling/docs in repo; **host injection not yet executed** → any prior long-run PASS remains “engineering evidence”, not “supervision-verified” under this FOUNDER rule.

## R1 — No instant death on short monitor blip

Default thresholds above. A 13-second-only kill policy is **rejected** unless founder-approved pre-run with proof of no false kill.

## R4 — Numbers must carry口径

Always state: timezone (prefer UTC in files), start/end, wall vs monotonic (`wall_elapsed_s`), definitions of cycle / with_work / idle.

## R5 — Triggers ≠ output

Reports must include: total triggers · effective work · idle/empty · business verdict separately.

## R6 — Project to Issue #9 within 24h local work

Paths + hashes on #9. Missing projection → joint acceptance discounted.

## R7 — Triage failures

| Class | Examples |
|-------|----------|
| Business | Verifier reject, task fail, budget block |
| Host | Reboot, WT/Explorer storm, disk full |
| Supervision | Wrong watch file, monitor crash, gap > red without DUT fault |

L2-4 closed as **INCOMPLETE**: supervision misconfiguration (wrong target) + host reboot — **not** scored as business FAIL.

`scripts/failure_attribution.py` can classify sample records into these three classes and reject unknown, empty, missing, free-text, and multi-class labels. That exercise does not attribute a live soak failure, does not satisfy founder condition 4, and does not start the clock.

## R8 — Host health

Known crash storm on founder Windows (2026-11-04 Application Error 1000 cluster). **No new high-frequency Interactive console long-run** without explicit founder approve after host status register.

## Mapping to code (current)

| Piece | Role |
|-------|------|
| `scripts/failure_attribution.py` | Classifies sample records into business, host, or supervision. Unknown, empty, missing, free-text, and multi-class labels are rejected. Sample classification is not a live soak attribution, does not satisfy founder condition 4, and does not start the clock |
| `scripts/stall_watchdog.py` | Progress age check; `--runner-glob` for L1 |
| `scripts/soak_2h.py` | DUT metrics; `max_wall_seconds`; finally metrics |
| `scripts/l2_2_score.py` | Offline 72h bundle scorer. Does not start a clock and does not register Interactive tasks |
| `scripts/coverage_gap_log.py` | Append-only gap line: `timestamp`, `gap_seconds`, `band` (`ok` / `yellow` / `red`), `source`. Does not complete a soak |
| `scripts/supervision_monitor.py` | Calls the logger. `--live-dut` is required before the source is `soak_summary_live` or `runner_glob_live` |
| `docs/progress/l2_2/R2_CHECKLIST.md` | Blank R2 note. Points at the logger. Does not start the clock |
| `docs/progress/EMERGENCY_STOP` | Human red stop |

## L2-2 scaffold

`docs/progress/l2_2/` defines the 72h duty as monotonic wall 259200s on the existing soak path. The clock is **NOT STARTED**. A missing R3 receipt stays supervision-unverified. Interactive console scheduled tasks stay out of scope (founder major gate, not requested here). The gap logger is `scripts/coverage_gap_log.py`. A gap line has `clock_effect: none` and does not replace the start decision in `docs/progress/l2_2/R2_CHECKLIST.md`.

## D1 historical note

D1 wall-clock ~86400s / with_work 1100 remains **business/host engineering evidence**. Under FOUNDER 2026-11-05, it was **not** preceded by R2 declaration + R3 injection → joint tag **未经验证** for supervision layer (does not erase D1 numbers).
