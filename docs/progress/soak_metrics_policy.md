# Soak metrics policy (2026-10-28 / updated 2026-10-31)

## Problem

Reporting `ok=120/120` from process exit codes alone misstated business progress.
Historical via-L1 2h: ~34 cycles with work, rest idle after queue drain.

FOUNDER-20261029-SOAK-24H: process ran **1326** cycles (exit0 all, with_work=1260, idle=66) but **metrics.json was not written** on exit → always use `finally` + checkpoints; rebuild tool available.

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
| final | true when written from soak finally or rebuild |

## Rules

1. Never claim business-closed-loop PASS from `cycles_exit0` alone.
2. Dual-track matrix must show **effective / total** and evidence binding strength.
3. Default `--idle-policy stop` after 3 consecutive idles.
4. Prefer `--seed >= --cycles` or `reseed` when testing long walls of time.
5. **`scripts/soak_2h.py` must write metrics in `finally`** and periodic checkpoint (`--metrics-every`).
6. If metrics missing but summary exists: `scripts/rebuild_soak_metrics_from_summary.py`.

## Evidence binding strength

- **strong**: full SHA + SHA256SUMS + artifacts reconcile
- **medium_plus**: full SHA + metrics.json + summary.jsonl (current target)
- **weak**: screenshots / verbal only

## 24h PARTIAL record (host-verified)

| Field | Value |
|-------|-------|
| sha | e3e8846 |
| segment | 2026-10-29T14:10:56Z → 2026-10-30T18:15:31Z |
| ran / planned | 1326 / 1440 |
| exit0 / with_work / idle | 1326 / 1260 / 66 |
| verdict | PARTIAL — not full 1440; not production |
