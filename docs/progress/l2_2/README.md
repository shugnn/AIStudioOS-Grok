# L2-2 — 72h wall soak (clock NOT STARTED)

Duty-cycle gate from `L2_NEXT_TIER.md`. This is **not** the 2026-11-07 product L2 (task split / worker), which stays **NOT STARTED**.

Production 7×24: **NOT ACCEPTED**. L2-2: **NOT STARTED**. This directory is a scaffold. No 72h clock was started.

L2-4 historical reconstruction for 2026-11-03..06 stays **INCOMPLETE** on [PR #11](https://github.com/shugnn/AIStudioOS-Grok/pull/11) (tip `931758cb7487d8c8ac1697f1b3ad1e2fa7610ef6`). That window is exhausted (`task_runs=0`, WT Error 1000 count 0). This scaffold does not relitigate it.

## What 72h means here

One continuous local duty on a single host, scored only after it exists:

| Rule | Meaning |
|------|---------|
| Wall | Monotonic `wall_elapsed_s` **≥ 259200** (`72 * 3600`) and `max_wall_seconds` **259200** |
| Driver | Existing `scripts/soak_2h.py --via-l1`. `cycles × interval` is not the wall |
| Business count | `cycles_with_work` (and idle) separate from `cycles_exit0`. Exit 0 is process success only |
| Heartbeat | Live soak `summary.jsonl` while that soak is the DUT. `runner-*.json` only when the DUT is L1 with no soak |
| Supervision | R2 written **before** start. Yellow gap 13s–5min is `coverage_gap`, not a business FAIL. Red gap **> 5 min** stops and seals as supervision failure |
| R3 | A receipt is required before any later **supervision-verified** tag. This scaffold does not run R3 |
| Stall | `scripts/stall_watchdog.py` (L2-1 code PASS) may watch a future **live** summary. The offline hook classifies synthetic fresh and stale files only. That code PASS is not a 72h PASS |
| Not this gate | Interactive / logon scheduled tasks, a 86400s wall, product L2 task-split, L2-3 kill recovery |

The committed Ubuntu-24H file `docs/progress/soak_2h/metrics.json` is wall **86400.001**. That length is below **259200**. `scripts/l2_2_preflight.py` reads the file as a historical **SHORT** specimen (`ubuntu_24h_specimen`): `ubuntu_24h_counts_as_72h` is false and `ubuntu_24h_used_as_dut` is false. The overall preflight `l2_2_status` and `clock_state` stay **NOT_STARTED**. The file is not wrapped as a started L2-2 capture, it does not count toward the 72h gate, and the stall hook does not use it as the DUT.

Ended SHORT walls are not additive. 72h is one continuous monotonic `wall_elapsed_s` ≥ **259200** on a single live soak. A sum of ended 24h walls does not count, including Ubuntu-24H **86400.001** plus another **86400**, and **86400 × 3** (that product is 259200 and is still not the gate). `scripts/l2_2_score.py` refuses a report that relabels such a sum as started, PASS, or ACCEPTED. No Windows D1 metrics file is committed in this tree (`afe25c2` is only a documented wall in `P0_STATUS.md`), so none is bound. This non-additivity gate is not a start.

## What is in the repo

| Piece | What it is |
|-------|------------|
| `scripts/l2_2_score.py` | Offline scorer. Emits `NOT_STARTED` or `INCOMPLETE`. `can_accept_l2_2`, `can_close_l2_2`, and `can_start_clock` stay false. Refuses `PASS`, production acceptance, and any sum of ended SHORT walls toward 259200 |
| `docs/progress/l2_2/SCHEMA.json` | Capture/report ids, 259200s wall, runner and watch rules |
| `tests/fixtures/l2_2/` | Synthetic captures dated **2026-02-01**. Not host evidence. Not the November incident |
| `tests/test_l2_2_score.py` | Short wall, exit0-only, full wall still refused, Interactive registration refused, forged PASS rejected |
| `docs/progress/l2_2/scaffold/report.json` | Score of the not-started fixture. Label `scaffold` |
| `scripts/l2_2_preflight.py` | Offline readiness check. Emits `NOT_STARTED`. Does not launch soak. `can_start_clock` stays false. Calls the stall-watchdog hook on synthetic temp summaries. Reads Ubuntu-24H `metrics.json` only as a historical SHORT specimen. Refuses additive 24h sums |
| `scripts/stall_watchdog.py` | L2-1 age check. The offline hook (`offline_probe`) classifies a synthetic fresh summary and a synthetic stale summary, composes `coverage_gap_log.py` bands, and does not write `docs/progress/STALL_ALERT.json`. It does not watch `docs/progress/soak_2h` and does not start the clock |
| `scripts/health_check.py` | One-shot local check. Re-runs this preflight, including the synthetic stall-watchdog hook and the Ubuntu-24H SHORT specimen binding, and scores the not-started fixture. Does not launch soak. Exit 0 is `overall_ok`, not a gate PASS and not a start. A pytest step in that command is the unit suite, not L2-2 acceptance |
| `docs/progress/l2_2/START_DECISION.md` | Blank start-decision template. Decision status **Not given**. Filling or committing it does not start the soak |
| `docs/progress/l2_2/scaffold/preflight.json` | Committed output of that check. Label `scaffold`. Not a start decision |
| `docs/progress/l2_2/SHA256SUMS.json` | Byte binding from `scripts/evidence_sha256sums.py`. Not a start, not a PASS, not production acceptance |
| `scripts/coverage_gap_log.py` | Append-only yellow/red/ok gap line. Does not start the clock |
| `docs/progress/l2_2/R2_CHECKLIST.md` | Blank R2 note that points at the logger |

Reproduce:

```bash
PYTHONPATH=. python scripts/l2_2_preflight.py
PYTHONPATH=. python scripts/health_check.py
PYTHONPATH=. python -m pytest tests/ -q
PYTHONPATH=. python scripts/l2_2_score.py \
  --capture tests/fixtures/l2_2/scaffold_clock_not_started.json
python scripts/evidence_sha256sums.py docs/progress/l2_2 --glob "**/*"
```

The sums command rewrites `SHA256SUMS.json` for the files in this directory. It does not launch the soak. A matching file is not a gate PASS and does not set `can_start_clock`. The preflight checks those bytes, except the digest of `scaffold/preflight.json` itself, which the tests recompute.

Exit 0 from the preflight means the not-started scaffold still matches this repo: the pieces are present, the documented soak flags parse, `R2_CHECKLIST.md` is still unfilled, `START_DECISION.md` is still the blank template with decision **Not given**, `docs/progress/EMERGENCY_STOP` is absent, the stall-watchdog hook classified a synthetic fresh summary (not stalled, gap band ok) and a synthetic stale summary (stalled, gap band red) without appending a gap line, the committed Ubuntu-24H metrics file is recorded as a historical SHORT specimen (wall 86400.001s, below 259200, not 72h evidence, not the stall DUT), and the scorer still refuses PASS / start / accept / close. Those synthetic stall files are temp files. The hook does not open `docs/progress/soak_2h` and does not leave `docs/progress/STALL_ALERT.json`. The specimen read does not start the clock. The non-additivity check records that those SHORT walls are not additive and does not start the clock. Exit 0 is an honest NOT STARTED report. It does **not** mean L2-2 passed, it does **not** set `can_start_clock`, and it does **not** launch `soak_2h.py`. Running the preflight is not a start decision. Filling the checklist is not a start decision. Filling `START_DECISION.md` is not a start decision. The stall hook is not a start and not L2-2 acceptance. A report that treats the Ubuntu-24H file as 72h evidence, as L2-2 acceptance, or as the live DUT fails closed.

`scripts/health_check.py` runs that same preflight and scores `tests/fixtures/l2_2/scaffold_clock_not_started.json`, then keeps the older local checks. Exit 0 there is `overall_ok` for those checks: `l2_2_status` / `clock_state` stay `NOT_STARTED`, the Ubuntu-24H specimen stays SHORT / not 72h / not the DUT, the soak was not launched, the three gates stay false, production 7×24 stays **NOT ACCEPTED**, `R2_CHECKLIST.md` is still the blank template, and `START_DECISION.md` is still **Not given**. A pytest run inside that command is the unit suite. It is not L2-2 acceptance and it is not a start decision. The check fails closed if a report flips a gate, if `START_DECISION.md` smuggles a start, PASS, ACCEPTED, or `can_start_clock` true, if a report treats the Ubuntu-24H file as 72h evidence, as acceptance, or as the stall DUT, or if a report adds historical 24h walls toward 259200. Writing that file is not a start. The non-additivity gate is not a start.

Exit 0 from the scorer means the report is an honest NOT STARTED or INCOMPLETE document. It does **not** mean L2-2 passed and it does **not** start a clock.

## Interactive duty is out of scope

Registering, creating, or enabling Interactive console scheduled tasks (10–15 minute console duty, `AIStudioOS-Grok-L1`, `AIStudioOS-Grok-Watchdog`) is a **founder major gate**. This scaffold does not request that enablement and does not treat it as approved. A bundle that registers those tasks is rejected by the scorer and still cannot accept the gate.

No scheduled task is created by `scripts/l2_2_score.py`.

## What remains before a real 72h can start

The clock stays **NOT STARTED** until a founder or worker explicitly decides to start the existing non-Interactive soak. This PR does not make that decision.

1. Leave L2-4 on PR #11. Do not re-capture 2026-11-03..06 in order to start L2-2.
2. Do not register Interactive console tasks.
3. Fill `docs/progress/l2_2/R2_CHECKLIST.md` before any process starts. The logger is `scripts/coverage_gap_log.py` (`band`: ok below 13s, yellow 13s–5min, red above 5min). Use `--live-dut` only for the live watch file. The checklist is not a start decision, and a gap line does not complete the soak. `docs/progress/l2_2/START_DECISION.md` stays **Not given** until a separate explicit decision. Filling that file alone does not start the soak. `scripts/l2_2_preflight.py` and `scripts/health_check.py` can be run at any time before that decision; running them is not the decision.
4. Only after that explicit start decision, on a host already allowed to run the local soak (the same free `soak_2h.py` path used for the 24h wall, not a new scheduled task):

```bash
PYTHONPATH=. python scripts/soak_2h.py --cycles 5000 --interval 60 --via-l1 --seed 300 \
  --idle-policy reseed --max-wall-seconds 259200
```

`cycles` must stay above `259200 / interval` so the stop reason can be `max_wall_seconds`. Point `stall_watchdog.py` at the **live** summary for that process, not at an ended experiment. The offline hook must not be aimed at the committed Ubuntu-24H files (`docs/progress/soak_2h`, wall 86400.001s). Those stay **SHORT**.

5. Score the resulting metrics with `scripts/l2_2_score.py`. Expect **INCOMPLETE**. The tool will still refuse PASS and will not accept production 7×24.
6. Run R3 injection and keep the receipt before anyone uses a supervision-verified tag. The observation track (DS) accepts or rejects. This scorer does not.
7. Product L2 (task split / worker) remains **NOT STARTED**. L2-3 remains a separate gate.
