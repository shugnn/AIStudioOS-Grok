# P1 scheduled trigger evidence (2026-10-24)

**Authorization**: Founder directed Grok to complete P1 three-fire evidence on this host (sandbox/local runner environment).

**Method**: `scripts/p1_scheduled_runner.sh` — local automatic scheduler (wall-clock spaced fires). System `crontab` binary not available in this environment; this script is the scheduled driver (not manual triple click).

| Fire | UTC time | exit | run_id |
|------|----------|------|--------|
| 1 | 2026-10-24T14:34:01Z | 0 | 20261024143401-869640 |
| 2 | 2026-10-24T14:34:30Z | 0 | 20261024143430-edf451 |
| 3 | 2026-10-24T14:34:58Z | 0 | 20261024143458-ee4e67 |

- Interval: 25s between fires
- Job: `dry_protocol_check` only (non-sensitive)
- Unique run_ids: 3, duplicates: 0
- Lock: fcntl (no double-owner)
- Budget USD: 0

Reproduce:
```bash
INTERVAL_SEC=25 RUNS=3 bash scripts/p1_scheduled_runner.sh
```

Artifacts in this directory + `scheduler.log`.
