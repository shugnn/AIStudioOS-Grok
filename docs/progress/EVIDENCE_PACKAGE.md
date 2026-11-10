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
| `scripts/l2_2_preflight.py` | Offline readiness check. Exit 0 is `NOT_STARTED`, not a gate PASS and not a start |
| `scripts/health_check.py` | Re-runs that preflight and scores the not-started fixture. Exit 0 is `overall_ok`, not a start and not acceptance. Its pytest step is the unit suite, not L2-2 acceptance |
| `tests/fixtures/l2_2/` | Synthetic **2026-02-01** captures |
| `scripts/coverage_gap_log.py` | Runtime gap lines only. A line is not soak completeness |
| `docs/progress/l2_2/R2_CHECKLIST.md` | Blank pre-start note. Clock stays **NOT STARTED** |

`cycles_exit0` and the Ubuntu-24H wall (86400.001s) do not accept this gate. L2-4 historical reconstruction for 2026-11-03..06 stays **INCOMPLETE** on [PR #11](https://github.com/shugnn/AIStudioOS-Grok/pull/11) (tip `931758cb7487d8c8ac1697f1b3ad1e2fa7610ef6`, `task_runs=0`, WT Error 1000 count 0). This package does not recapture that window. Host captures stay on that PR.

## Commands

```powershell
py -3 scripts/soak_2h.py --cycles 10 --interval 2 --via-l1 --idle-policy stop
py -3 scripts/evidence_sha256sums.py docs/progress/soak_2h
py -3 scripts/evidence_sha256sums.py docs/progress/l2_2 --glob "**/*"
```

The L2-2 sums command only rewrites `docs/progress/l2_2/SHA256SUMS.json`. It does not launch `soak_2h.py` and does not start the 72h clock. `git_head` in that file is the commit the hasher saw when it ran, not a later start.

## Dual-track note

ChatGPT evidence lives under their `docs/evidence/`. Cross-review on their Issue #11 / PR history; do not copy their files into this repo.
