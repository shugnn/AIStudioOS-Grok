# P0 status snapshot — AIStudioOS-Grok (2026-11-07)

**Issue**: [#9](https://github.com/shugnn/AIStudioOS-Grok/issues/9)  
**Production 7×24**: **NOT ACCEPTED**  
**main tip**: `b4306f5` (Ubuntu-24H metrics on main)

## Done

| Item | Evidence |
|------|----------|
| CP + Exp-02/03/04 | main history |
| L1 cross-platform lock | msvcrt Windows · **fcntl Linux** |
| OS schtasks ≥3 | runner-20261027* (Windows) |
| Honest soak metrics + wall clock | `--max-wall-seconds` |
| Emergency stop | L1 exit 3 + soak |
| Supervision R1–R8 ACK | `SUPERVISION_POLICY.md` |
| **R3 injection** | **PASS** Ubuntu `r3-ubuntu-20261105T094732Z` |
| **D1 Windows 24h wall** | PASS wall 86400 · afe25c2 |
| **Ubuntu-24H wall** | **PASS** wall 86400.001 · aaf8d24 · 1233 cycles · with_work 1185 |
| Cross-review ChatGPT | Issue #11 continuous |

### FOUNDER Ubuntu-24H (final)

| Field | Value |
|-------|-------|
| sha | aaf8d24 |
| host | Laisg-Ubuntu |
| wall_elapsed_s | **86400.001** |
| final | true |
| stopped_early | max_wall_seconds |
| exit0 / with_work / idle | 1233 / 1185 / 48 |
| metrics on main | `docs/progress/soak_2h/metrics.json` |

## Open (founder-gated or blocked)

| ID | Notes |
|----|-------|
| L2-4 | **INCOMPLETE**. Host capture from `LAPTOP-Q14O4JJT` is in `docs/progress/l2_4/host/` (`host_capture_unverified`). Window 2026-11-03 → 2026-11-06. WT Application Error 1000 count **0** (1× Explorer.EXE only). `task_runs=0` because Task Scheduler Operational is disabled. Not a duty-cycle PASS. |
| L2-2 72h | not started |
| L2-5/6 | default deny |
| J-Exp-01 | design only until ACK |
| summary.jsonl full push | large; host Token/SSH |

## L2-4 host capture (2026-11-09, LAPTOP-Q14O4JJT)

Files: `docs/progress/l2_4/host/capture.json`, `report.json`, `SHA256SUMS.json`. Label **host_capture_unverified**. Gate **INCOMPLETE**. Production 7×24 **NOT ACCEPTED**.

| Field | Value |
|-------|--------|
| Window | 2026-11-03T00:00:00Z → 2026-11-06T00:00:00Z |
| Collector | `scripts/l2_4_capture_host.ps1` (`read_only`); host `git_sha` `3402e9b` |
| WT errors | **0**. Application Error 1000 in window: 1× `Explorer.EXE` only |
| Reboots | 6 events in file (1074, 6005, 6006, 12). `reboot_residue.detected=false`. Tasks were not registered |
| Scheduler | `task_runs=0`. Operational log **disabled** (`task_history.available=false`) → `scheduler_history_not_in_capture` |
| Wakes | `wake_count=133` from `runner-*.json` only. `wake_bar_20_met=true`. `correlation.basis=runner_artifacts_only`, `strength=no_events` |
| Report gates | `can_close_l2_4=false`, `verified=false`, `causation=not_proven` |

Do not enable the Task Scheduler Operational log or re-add Interactive console tasks from this change. Next founder decision is whether to enable that history and re-capture (read-only). Scaffold fixtures under `tests/fixtures/l2_4/` stay synthetic. Product L2 (task split / worker) remains **not started**.

## Stop

```bash
touch docs/progress/EMERGENCY_STOP
rm -f docs/progress/EMERGENCY_STOP
```
