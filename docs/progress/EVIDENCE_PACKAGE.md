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

Clock **NOT STARTED**. Gate **NOT ACCEPTED**. No Interactive scheduled task is registered by this package.

| File | Role |
|------|------|
| `SCHEMA.json` | Capture/report contract. Wall bar is monotonic **259200s** |
| `scaffold/report.json` | Score of the not-started fixture. Not host evidence |
| `scripts/l2_2_score.py` | Offline scorer. Exit 0 is an honest report, not a PASS |
| `tests/fixtures/l2_2/` | Synthetic **2026-02-01** captures |

`cycles_exit0` and the Ubuntu-24H wall (86400.001s) do not accept this gate. L2-4 host files, when present, stay on PR #11 and are a different gate.

## Commands

```powershell
py -3 scripts/soak_2h.py --cycles 10 --interval 2 --via-l1 --idle-policy stop
py -3 scripts/evidence_sha256sums.py docs/progress/soak_2h
```

## Dual-track note

ChatGPT evidence lives under their `docs/evidence/`. Cross-review on their Issue #11 / PR history; do not copy their files into this repo.
