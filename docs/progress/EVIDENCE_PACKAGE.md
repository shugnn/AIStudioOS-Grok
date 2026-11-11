# Evidence package layout (Grok track)

Standard directories and files for dual-track review. Zero paid. No production claim.

## Binding strength

| Level | Required |
|-------|----------|
| weak | Screenshots / chat only |
| medium | `git` SHA + paths in Issue |
| medium–strong | + `SHA256SUMS.json` via `scripts/evidence_sha256sums.py` |
| strong | SUMS + fixed file list + independent reconcile of artifacts |

## Soak (`docs/progress/soak_2h/`)

| File | Role |
|------|------|
| `metrics.json` | **Required.** `cycles_exit0`, `cycles_with_work`, `cycles_idle`, `sha_full`, `idle_policy` |
| `summary.jsonl` | Per-cycle rows (`with_work`, `idle`, `steps_this_wake`) |
| `soak.log` | Human-readable stream |
| `SHA256SUMS.json` | Optional upgrade to medium–strong |

**Never** report business PASS from `cycles_exit0` alone.

## L1 / scheduler

| Path | Role |
|------|------|
| `docs/progress/runner-*.json` | Per L1 wake artifact (`lock`, `platform`, jobs) |
| `docs/progress/.l1_runner.lock` | Runtime only (gitignored) |

OS scheduler: keep `Get-ScheduledTaskInfo` + ≥3 runner JSON timestamps in Issue #9.

## Control Plane exp state

| Path | Role |
|------|------|
| `docs/progress/exp02_auto_loop/state/` | Live `cp_state.json` / `goal_id.txt` (**gitignored** except `.gitkeep`) |
| `docs/progress/exp02_auto_loop/exp02b-*.json` | Run reports (committable) |
| `docs/progress/exp03_crash_recovery/` | Crash recovery evidence |
| `docs/progress/exp04_cancel_stress/` | Cancel + long queue |

## L2-2 72h scaffold (`docs/progress/l2_2/`)

Clock **NOT STARTED**. L2-2 gate **NOT ACCEPTED**. Production 7×24 **NOT ACCEPTED**. No Interactive scheduled task is registered by this package. `SHA256SUMS.json` is the medium–strong byte binding for this tree. Matching sums do not start the 72h clock, do not accept the gate, and do not close L2-2.

| File | Role |
|------|------|
| `SCHEMA.json` | Capture/report contract. Wall bar is monotonic **259200s** |
| `README.md` | Scaffold index. Clock stays **NOT STARTED** |
| `scaffold/report.json` | Score of the not-started fixture. Not host evidence |
| `scaffold/preflight.json` | Offline preflight report from `scripts/l2_2_preflight.py`. Status `NOT_STARTED`. Not a start decision |
| `SHA256SUMS.json` | SHA-256 binding written by `scripts/evidence_sha256sums.py` (`--glob "**/*"`). Not a PASS |
| `scripts/l2_2_score.py` | Offline scorer. Exit 0 is an honest report, not a PASS |
| `scripts/l2_2_preflight.py` | Offline readiness check. Exit 0 is `NOT_STARTED`, not a gate PASS and not a start. Includes the stall-watchdog hook, the Ubuntu-24H historical SHORT specimen binding, the non-additivity gate (ended 24h walls do not sum to 72h), the process-boundary continuity gate (sequential or restarted soaks do not stitch into 72h), the founder-start honesty gate (Issue #9 comment 6761044915 is a conditional approval, not a start; the five conditions stay unsatisfied), and the offline supervisor-watchdog honesty gate (synthetic files only; not founder condition 2; not a start). It also runs `scripts/supervisor_watchdog.py` on a dummy process, `scripts/supervision_cadence.py` on a short time-compressed interval, `scripts/failure_attribution.py` on sample records, and `scripts/public_evidence_pack.py` on sample public-shaped packs, and `scripts/supervision_policy.py` on sample bands and monotonic sequences, and `scripts/start_readiness.py` to aggregate those sample checkers. The watchdog and cadence exercises are not founder condition 2. The sample classification is not founder condition 4. The sample public pack is not founder condition 3. The sample policy check is not founder condition 1. The sample aggregate does not satisfy any founder condition and does not allow `can_start_clock`. LOCAL_ONLY does not count. `SHA256SUMS.json` is not live soak evidence. None of them is a start |
| `scripts/stall_watchdog.py` | Offline hook classifies synthetic fresh vs stale summaries and composes `scripts/coverage_gap_log.py` bands. Does not watch Ubuntu-24H, does not write `STALL_ALERT.json`, and does not start the clock |
| `scripts/health_check.py` | Re-runs that preflight, including the synthetic stall-watchdog hook, the Ubuntu-24H SHORT specimen, the non-additivity gate, the process-boundary continuity gate, the founder-start honesty gate, and the offline supervisor-watchdog honesty gate, plus the dummy supervisor-watchdog exercise, the time-compressed supervision-cadence exercise, the sample failure-attribution exercise, the sample public evidence-pack exercise, the sample supervision-policy check, and the sample start-readiness aggregate, and scores the not-started fixture. Exit 0 is `overall_ok`, not a start and not acceptance. Its pytest step is the unit suite, not L2-2 acceptance |
| `tests/fixtures/l2_2/` | Synthetic **2026-02-01** captures |
| `scripts/coverage_gap_log.py` | Runtime gap lines only. A line is not soak completeness |
| `docs/progress/l2_2/R2_CHECKLIST.md` | Blank pre-start note. Clock stays **NOT STARTED** |
| `docs/progress/l2_2/START_DECISION.md` | Blank start-decision template. Decision status **Not given**. Filling this file alone does not start the soak |

`cycles_exit0` and the Ubuntu-24H wall (86400.001s) do not accept this gate. The offline preflight records `docs/progress/soak_2h/metrics.json` as a historical SHORT specimen: the wall is below 259200s, it does not count as 72h evidence, and it is not the stall DUT. Ended SHORT walls are not additive. A sum of 24h walls, including 86400.001 plus another 86400 and 86400 times 3, is not a started L2-2 capture. That gate is not a start. Stitching sequential or restarted soak invocations, even back-to-back on the same host, is not a started L2-2 capture. That continuity gate is not a start. Issue #9 comment 6761044915 is a conditional founder approval and is not a start. The five conditions stay unsatisfied. LOCAL_ONLY is not public evidence. Unknown root cause is not a terminal attribution. The soak-DUT stall watchdog is not a watchdog of the supervisor. That founder-start gate is not a start. An offline probe of synthetic supervisor-alive and supervisor-crash-unrecorded files does not satisfy founder condition 2, is not a watchdog of a live supervisor, and is not a start. A dummy-process crash record from `scripts/supervisor_watchdog.py` does not satisfy founder condition 2 and is not a start. A short time-compressed exercise of `scripts/supervision_cadence.py` does not demonstrate a supervision write every 10 minutes and is not a start. A sample classification from `scripts/failure_attribution.py` does not satisfy founder condition 4, does not attribute a live soak failure, and is not a start. A sample public pack from `scripts/public_evidence_pack.py` does not satisfy founder condition 3, does not pack live soak evidence, and is not a start. A sample supervision-policy check from `scripts/supervision_policy.py` does not satisfy founder condition 1 and is not a start. A sample aggregate from `scripts/start_readiness.py` does not satisfy any founder condition, does not treat a 72h result or the Ubuntu-24H 86400.001s SHORT wall as production readiness, and is not a start. LOCAL_ONLY does not count. `SHA256SUMS.json` is scaffold bytes only. Overall L2-2 status stays **NOT STARTED**. T2 (`DS-T2-20261110`) is **ACCEPTED** on the observation track. Product L2 was recorded as **CONDITIONAL**, not granted, pending T3, in earlier observation comments. Issue #9 comment 6776483825 (2026-11-10T19:00:37Z) later recorded an observation-track acceptance of T3 and product L2, void if plan.json was handwritten to fool the check. This package does not re-claim that verdict and does not grant product L2. L2-4 historical reconstruction for 2026-11-03..06 stays **INCOMPLETE** on [PR #11](https://github.com/shugnn/AIStudioOS-Grok/pull/11) (tip `931758cb7487d8c8ac1697f1b3ad1e2fa7610ef6`, `task_runs=0`, WT Error 1000 count 0). This package does not recapture that window. Host captures stay on that PR.

## Commands

```powershell
py -3 scripts/soak_2h.py --cycles 10 --interval 2 --via-l1 --idle-policy stop
py -3 scripts/evidence_sha256sums.py docs/progress/soak_2h
py -3 scripts/evidence_sha256sums.py docs/progress/l2_2 --glob "**/*"
```

The L2-2 sums command only rewrites `docs/progress/l2_2/SHA256SUMS.json`. It does not launch `soak_2h.py` and does not start the 72h clock. `git_head` in that file is the commit the hasher saw when it ran, not a later start.

## Dual-track note

ChatGPT evidence lives under their `docs/evidence/`. Cross-review on their Issue #11 / PR history; do not copy their files into this repo.
