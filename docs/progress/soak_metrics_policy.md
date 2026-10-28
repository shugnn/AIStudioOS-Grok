# Soak metrics policy (2026-10-28)

## Problem

Reporting `ok=120/120` from process exit codes alone misstated business progress.
Historical via-L1 2h: ~34 cycles with work, rest idle after queue drain.

## Required fields (`docs/progress/soak_2h/metrics.json`)

| Field | Meaning |
|-------|---------|
| cycles_planned / cycles_ran | scheduled vs actually executed |
| cycles_exit0 | process/L1 exit 0 |
| cycles_with_work | steps_this_wake>0 or accepted growth |
| cycles_idle | exit0 and no work |
| tasks_done_unique_est | estimated unique completions |
| sha_full | git HEAD at soak start |
| idle_policy | continue \| stop \| reseed |

## Rules

1. Never claim business-closed-loop PASS from `cycles_exit0` alone.
2. Dual-track matrix must show **effective / total** and evidence binding strength.
3. Default `--idle-policy stop` after 3 consecutive idles.
4. Prefer `--seed >= --cycles` or `reseed` when testing long walls of time.

## Evidence binding strength

- **strong**: full SHA + SHA256SUMS + artifacts reconcile
- **medium_plus**: full SHA + metrics.json + summary.jsonl (current target)
- **weak**: screenshots / verbal only
