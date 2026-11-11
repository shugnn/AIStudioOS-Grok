# Start decision — blank template (clock NOT STARTED)

This file is the note an operator would fill before any future L2-2 soak. The copy in git is unfilled.

L2-2 clock: **NOT STARTED**. Production 7×24: **NOT ACCEPTED**. `can_start_clock`, `can_accept_l2_2`, and `can_close_l2_2` stay false. Writing or committing this template does not start the soak and does not start `--max-wall-seconds 259200`.

Filling this file alone does not start the soak. It does not launch `scripts/soak_2h.py`. A filled copy is still not a launch.

Interactive console scheduled tasks (`AIStudioOS-Grok-L1`, Watchdog) stay a founder major gate and are out of scope. Do not register, create, or enable them.

## Fields

| Field | This template | Operator fills only under a separate explicit decision |
|-------|----------------|--------------------------------------------------------|
| Decision status | **Not given** | Separate explicit decision required before any launch. This cell is not a launch |
| Who | unfilled | Name of the person who would decide |
| UTC time | unfilled | UTC timestamp of that decision |
| Host | unfilled | Host name for the future soak |
| Intended command | `scripts/soak_2h.py --via-l1 --idle-policy reseed --max-wall-seconds 259200` | Documented only. Copying this cell does not launch it |
| This file | Filling this file alone does not start the soak | A filled copy is still not a launch |

The intended command is the existing non-Interactive local soak. This template does not execute it.

## Not a start

- Writing or committing this template is not a start.
- Filling these cells is not a start.
- `scripts/l2_2_preflight.py` and `scripts/health_check.py` read this file only to confirm it is still blank. Running either check is not a start.
- Exit 0 from those checks is an honest NOT STARTED report. The three gates stay false. Production 7×24 stays **NOT ACCEPTED**.
- The offline non-additivity gate is not a start.
- The offline process-boundary continuity gate is not a start.
- The conditional founder approval on Issue #9 is not a start.
- Recording the five unfilled conditions is not a start.
- The offline supervisor-watchdog probe is not a start. It classifies synthetic files only. It does not satisfy founder condition 2 and it is not a watchdog of a live supervisor. `scripts/stall_watchdog.py` is not that watchdog.
- The dummy supervisor-watchdog exercise is not a start. `scripts/supervisor_watchdog.py` can write a crash record within 10 seconds for a process it was pointed at. Dummy-process success does not satisfy founder condition 2 and does not demonstrate a supervision write every 10 minutes. A crash record 11 seconds later does not meet the 10-second requirement.
- The time-compressed supervision-cadence exercise is not a start. `scripts/supervision_cadence.py` can write supervision records on a short interval. The intended production bound is 600 seconds. That short exercise does not demonstrate a supervision write every 10 minutes and does not satisfy founder condition 2. A write later than 600 seconds does not meet the cadence bound. `scripts/stall_watchdog.py` and `scripts/supervisor_watchdog.py` are not that writer.
- The sample failure-attribution exercise is not a start. `scripts/failure_attribution.py` classifies synthetic records into business, host, or supervision. Unknown, empty, missing, and other free-text labels are rejected. A record that names more than one class without a single terminal class is rejected. Classifying those samples does not satisfy founder condition 4 and does not attribute a live soak failure.
- The sample public-evidence exercise is not a start. `scripts/public_evidence_pack.py` can validate a sample pack that has final metrics, a log summary, and a SHA list. It refuses a LOCAL_ONLY pack. It refuses a pack missing any of those pieces. `docs/progress/l2_2/SHA256SUMS.json` is not soak evidence. Validating that sample does not satisfy founder condition 3.
- The sample supervision-policy exercise is not a start. `scripts/supervision_policy.py` checks that the committed gap bands are yellow from 13s through 300s inclusive and red strictly above 300s, classifies sample gaps through `scripts/coverage_gap_log.py`, and rejects a backward timestamp or `mono_seconds` jump. Matching those constants does not satisfy founder condition 1. `condition_1_satisfied` stays false.
- The sample start-readiness aggregate is not a start. `scripts/start_readiness.py` reads the sample checkers for conditions 1–4 and refuses a sample report that claims production 7×24 or that treats a 72h result or the Ubuntu-24H 86400.001s SHORT wall as production readiness. Those sample results do not satisfy any founder condition and do not allow `can_start_clock`. `condition_5_satisfied` stays false.

## Conditional founder approval (not a start)

Issue #9 comment `6761044915` at `2026-11-10T06:50:14Z` records a conditional founder approval for the 72h long test on PR #12. That approval is real. It is not a start. It does not set `can_start_clock`. Approval without the five conditions below, and without a later explicit start registration, is not a start. This file does not post that registration.

| Condition | This template |
|-----------|----------------|
| Supervision policy | Unfilled. Yellow is 13s through 300s. Red is above 300s. The clock is monotonic. Writing the bands here is not a declaration before a launch. `scripts/supervision_policy.py` can classify sample gaps and sample monotonic sequences. That sample does not fill this cell and does not satisfy founder condition 1 |
| Supervision cadence and supervisor watchdog | Unfilled. A supervision writer has to record at least once every 10 minutes on a live L2-2 supervisor. `scripts/supervision_cadence.py` can write on a configured interval whose intended bound is 600 seconds. The short exercise does not fill this cell. The supervisor itself would need another process to record a crash within 10s. `scripts/stall_watchdog.py` watches a soak DUT. It is not that supervisor watchdog and it is not the cadence writer. `scripts/supervisor_watchdog.py` can watch a pid and write a crash record within 10 seconds. A dummy-process exercise does not fill this cell and it is not the cadence writer |
| Public evidence | Unfilled. Final metrics, a log summary, and a SHA list would have to be committed in public. LOCAL_ONLY does not count. `scripts/public_evidence_pack.py` can validate a sample public-shaped pack and refuses LOCAL_ONLY and a pack missing any piece. That sample does not fill this cell and does not satisfy founder condition 3. `SHA256SUMS.json` is not that pack |
| Failure attribution | Unfilled. A failure would have to name business, host, or supervision. Unknown root cause is not a terminal attribution. `scripts/failure_attribution.py` can classify sample records into those three classes and rejects unknown, empty, missing, free-text, and multi-class labels. That sample classification does not fill this cell, does not satisfy founder condition 4, and is not a live soak attribution |
| Production 7×24 | Stays **NOT ACCEPTED**. A 72h result is not production readiness. `scripts/start_readiness.py` can refuse a sample report that claims production 7×24 or that treats a 72h result or the Ubuntu-24H 86400.001s SHORT wall as production readiness. That sample refusal does not fill this cell and does not satisfy founder condition 5 |

The later registration line is not in this file. Its shape, which this template does not fill, is:

    L2-2 START: utc=<T0> sha=<full SHA> host=<host> max_wall_seconds=259200
    supervision: yellow=13s-300s red=>300s watchdog=<mechanism>

Copying that shape is not a launch.
