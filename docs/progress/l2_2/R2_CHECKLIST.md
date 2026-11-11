# R2 checklist — fill before any future L2-2 start

This file is the note an operator copies **before** a soak start. The copy in git is unfilled.

L2-2 clock: **NOT STARTED**. Production 7×24: **NOT ACCEPTED**. `can_start_clock`, `can_accept_l2_2`, and `can_close_l2_2` stay false. Writing or committing this checklist does not start `--max-wall-seconds 259200`.

Interactive console scheduled tasks stay a founder major gate. Do not register them.

## Declare

| Item | This template | Operator fills before a real start |
|------|----------------|-------------------------------------|
| Start decision | **Not given** | Who decided, and the UTC time. Until that line exists, do not launch soak |
| DUT | none running for L2-2 | `scripts/soak_2h.py --via-l1` only after the decision |
| Watch file | do not use the committed ended `summary.jsonl` as if it were live | The summary file created by **this** process, or `runner-*.json` only when the DUT is L1 and no soak is running |
| Logger | `scripts/coverage_gap_log.py` | Same helper. One JSON object per line |
| Log path | none committed | Operator path. The monitor writes `docs/progress/coverage_gaps.jsonl` only while that process is actually running |
| Source | `soak_summary_path` unless `--live-dut` is set on the live file | `soak_summary_live` or `runner_glob_live` only with `--live-dut`. That flag is a claim, not proof |
| Yellow | 13s through 300s inclusive | Append a record. `coverage_gap` true. **Not** a business FAIL |
| Red | `gap_seconds` > 300, or the signal file is missing | Append a record. Supervision failure. Stop and seal if this monitor owns the DUT |
| Ok | `gap_seconds` < 13 | Appended only when a yellow or red gap recovers. Not soak completeness |
| Record | `timestamp`, `gap_seconds`, `band`, `source` | Also `mono_seconds` while the monitor is running, `implies_soak_complete: false`, `clock_effect: none` |

## Sample (not a host gap)

```bash
PYTHONPATH=. python scripts/coverage_gap_log.py \
  --gap-seconds 30 --source operator_sample \
  --timestamp 2026-02-01T00:00:30Z --out /tmp/coverage-gap-sample.jsonl
```

`operator_sample` is a scratch classification. It is not the Ubuntu-24H summary and not a 72h run. The committed `docs/progress/soak_2h/metrics.json` (wall 86400.001s) is a historical SHORT specimen. The offline preflight records that it is below 259200, that it does not count toward the 72h gate, and that it is not the stall DUT. That binding does not start the 72h clock. Ended SHORT walls are not additive toward 259200. Recording that rule is not a start. Stitching sequential or restarted soak invocations into one capture is not a continuous 72h wall. Recording that rule is not a start.

## Founder start conditions (unfilled)

Issue #9 comment 6761044915 (2026-11-10T06:50:14Z) is a conditional founder approval. It is not a start. The five conditions are unfilled here: supervision policy (yellow 13s through 300s, red above 300s, monotonic clock), supervision writes at least once every 10 minutes plus a watchdog of the supervisor itself (a soak-DUT stall watchdog does not count; a crash of the supervisor must be recorded by another process within 10s), public evidence (final metrics, log summary, and a SHA list; LOCAL_ONLY does not count), three-way failure attribution (business / host / supervision; unknown root cause is not a terminal attribution), and no production 7×24 claim (a 72h result is not production readiness). Recording this list is not a start. `can_start_clock` stays false. An offline probe of synthetic supervisor-alive and supervisor-crash-unrecorded files is not that supervisor watchdog and is not a start. `scripts/failure_attribution.py` can classify sample records into business, host, or supervision and reject unknown, empty, missing, free-text, and multi-class labels. That sample classification does not fill the failure-attribution condition and is not a start. `scripts/public_evidence_pack.py` can validate a sample public-shaped pack (final metrics, a log summary, and a SHA list) and refuses LOCAL_ONLY. That sample does not fill the public-evidence condition and is not a start. `SHA256SUMS.json` is not that pack. `scripts/supervision_policy.py` can check the committed yellow 13s–300s / red-above-300s bands and sample monotonic sequences. That sample does not fill the supervision-policy condition, does not satisfy founder condition 1, and is not a start.

## Still required before `--max-wall-seconds 259200`

1. An explicit start decision. This checklist is not that decision.
2. The watch file must be the live DUT. Do not point the logger at an ended experiment.
3. Pass `--live-dut` to `scripts/supervision_monitor.py` only for that live file.
4. Do not register Interactive console tasks.
5. After a real run, score with `scripts/l2_2_score.py` and expect **INCOMPLETE**.
6. An R3 receipt is still required before any supervision-verified tag. The observation track accepts or rejects.

## Offline preflight

`python scripts/l2_2_preflight.py` only checks this blank note and the rest of the scaffold. Running it is not a start decision. Filling this file is not a start decision. The 72h clock stays **NOT STARTED** until a separate explicit decision.
