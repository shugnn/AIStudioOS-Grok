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

## Conditional founder approval (not a start)

Issue #9 comment `6761044915` at `2026-11-10T06:50:14Z` records a conditional founder approval for the 72h long test on PR #12. That approval is real. It is not a start. It does not set `can_start_clock`. Approval without the five conditions below, and without a later explicit start registration, is not a start. This file does not post that registration.

| Condition | This template |
|-----------|----------------|
| Supervision policy | Unfilled. Yellow is 13s through 300s. Red is above 300s. The clock is monotonic. Writing the bands here is not a declaration before a launch |
| Supervision cadence and supervisor watchdog | Unfilled. A future supervision writer would have to record at least once every 10 minutes. The supervisor itself would need another process to record a crash within 10s. `scripts/stall_watchdog.py` watches a soak DUT. It is not that supervisor watchdog |
| Public evidence | Unfilled. Final metrics, a log summary, and a SHA list would have to be committed in public. LOCAL_ONLY does not count |
| Failure attribution | Unfilled. A failure would have to name business, host, or supervision. Unknown root cause is not a terminal attribution |
| Production 7×24 | Stays **NOT ACCEPTED**. A 72h result is not production readiness |

The later registration line is not in this file. Its shape, which this template does not fill, is:

    L2-2 START: utc=<T0> sha=<full SHA> host=<host> max_wall_seconds=259200
    supervision: yellow=13s-300s red=>300s watchdog=<mechanism>

Copying that shape is not a launch.
