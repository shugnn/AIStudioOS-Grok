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
