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
| Stall | `scripts/stall_watchdog.py` (L2-1 code PASS) may watch the live summary during a future run. That code PASS is not a 72h PASS |
| Not this gate | Interactive / logon scheduled tasks, a 86400s wall, product L2 task-split, L2-3 kill recovery |

The committed Ubuntu-24H file `docs/progress/soak_2h/metrics.json` is wall **86400.001**. The scorer treats that length as **SHORT**. It is not relabelled as 72h.

## What is in the repo

| Piece | What it is |
|-------|------------|
| `scripts/l2_2_score.py` | Offline scorer. Emits `NOT_STARTED` or `INCOMPLETE`. `can_accept_l2_2`, `can_close_l2_2`, and `can_start_clock` stay false. Refuses `PASS` and production acceptance |
| `docs/progress/l2_2/SCHEMA.json` | Capture/report ids, 259200s wall, runner and watch rules |
| `tests/fixtures/l2_2/` | Synthetic captures dated **2026-02-01**. Not host evidence. Not the November incident |
| `tests/test_l2_2_score.py` | Short wall, exit0-only, full wall still refused, Interactive registration refused, forged PASS rejected |
| `docs/progress/l2_2/scaffold/report.json` | Score of the not-started fixture. Label `scaffold` |
| `scripts/coverage_gap_log.py` | Append-only yellow/red/ok gap line. Does not start the clock |
| `docs/progress/l2_2/R2_CHECKLIST.md` | Blank R2 note that points at the logger |

Reproduce:

```bash
PYTHONPATH=. python -m pytest tests/test_l2_2_score.py -q
PYTHONPATH=. python scripts/l2_2_score.py \
  --capture tests/fixtures/l2_2/scaffold_clock_not_started.json
```

Exit 0 means the report is an honest NOT STARTED or INCOMPLETE document. It does **not** mean L2-2 passed and it does **not** start a clock.

## Interactive duty is out of scope

Registering, creating, or enabling Interactive console scheduled tasks (10–15 minute console duty, `AIStudioOS-Grok-L1`, `AIStudioOS-Grok-Watchdog`) is a **founder major gate**. This scaffold does not request that enablement and does not treat it as approved. A bundle that registers those tasks is rejected by the scorer and still cannot accept the gate.

No scheduled task is created by `scripts/l2_2_score.py`.

## What remains before a real 72h can start

The clock stays **NOT STARTED** until a founder or worker explicitly decides to start the existing non-Interactive soak. This PR does not make that decision.

1. Leave L2-4 on PR #11. Do not re-capture 2026-11-03..06 in order to start L2-2.
2. Do not register Interactive console tasks.
3. Fill `docs/progress/l2_2/R2_CHECKLIST.md` before any process starts. The logger is `scripts/coverage_gap_log.py` (`band`: ok below 13s, yellow 13s–5min, red above 5min). Use `--live-dut` only for the live watch file. The checklist is not a start decision, and a gap line does not complete the soak.
4. Only after that explicit start decision, on a host already allowed to run the local soak (the same free `soak_2h.py` path used for the 24h wall, not a new scheduled task):

```bash
PYTHONPATH=. python scripts/soak_2h.py --cycles 5000 --interval 60 --via-l1 --seed 300 \
  --idle-policy reseed --max-wall-seconds 259200
```

`cycles` must stay above `259200 / interval` so the stop reason can be `max_wall_seconds`. Point `stall_watchdog.py` at the **live** summary for that process, not at an ended experiment.

5. Score the resulting metrics with `scripts/l2_2_score.py`. Expect **INCOMPLETE**. The tool will still refuse PASS and will not accept production 7×24.
6. Run R3 injection and keep the receipt before anyone uses a supervision-verified tag. The observation track (DS) accepts or rejects. This scorer does not.
7. Product L2 (task split / worker) remains **NOT STARTED**. L2-3 remains a separate gate.
