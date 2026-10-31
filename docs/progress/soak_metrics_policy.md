# Soak metrics policy (updated 2026-10-31)

## Rules

1. Never claim business PASS from `cycles_exit0` alone.
2. Report **cycles_with_work / cycles_ran** and idle separately.
3. Prefer `--seed` sized to work or `--idle-policy reseed`.
4. Write `metrics.json` in **finally** + periodic checkpoint.
5. **`--max-wall-seconds`** uses monotonic clock — do **not** treat `cycles × interval` as exact wall time.
6. Rebuild from summary if final metrics missing: `scripts/rebuild_soak_metrics_from_summary.py`.

## FOUNDER-20261029-SOAK-24H

| Field | Value |
|-------|-------|
| ran / planned | 1330 / 1440 |
| with_work / idle | 1264 / 66 |
| verdict | PARTIAL |
| hashes | `docs/progress/soak_2h/SHA256SUMS.json` |

Production 7×24: **NOT ACCEPTED**.
