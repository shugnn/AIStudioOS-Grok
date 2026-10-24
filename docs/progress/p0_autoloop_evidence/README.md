# P0 AUTOLOOP evidence (FOUNDER-20261024-AUTOLOOP)

**Environment**: isolated sandbox Linux, zero paid services, no production deploy.

## Verified

| # | Criterion | Evidence |
|---|-----------|----------|
| 1 | ≥3 scheduler-triggered cycles | `03_three_wakes.log` — wakes at 16:26:50Z, 16:27:07Z, 16:27:24Z; L1 `auto_loop_once`; exit 0 |
| 2 | NEW→execute→independent VERIFY→ACCEPTED | `01_full_success.stdout.txt` — 4/4 accepted under Control Plane |
| 3a | Verifier rejects bad worker output | `02_inject_fail_retry.stdout.txt` — fail_once rejected (Worker wrong count) |
| 3b | Limited retry re-propose | same — accepted 5 after 1 reject (retry path) |
| 3c | Lock contention skip | `05_lock_skip.stdout.txt` — exit 2 `lock_held` |
| 4 | Budget hard block | `04_budget_block.json` — status blocked, policy budget |
| 5 | Cost / human | spent $0, human_interventions 0 in loop reports |

## Not claimed / not verified

- LLM-based autonomous Manager
- Host OS crontab installed on founder laptop (sandbox uses local spaced scheduler + L1 wakes)
- Cross-host 7×24 daemon
- ChatGPT independent re-run of these tests

## Reproduce

```bash
python3 experiments/exp02_auto_loop/cp_driven_loop.py --reset --max-steps 10
python3 experiments/exp02_auto_loop/cp_driven_loop.py --reset --inject-fail --max-steps 12
# seed then 3 wakes:
python3 -c "from experiments.exp02_auto_loop.cp_driven_loop import run; run(max_steps=0)"
for i in 1 2 3; do python3 scripts/l1_runner.py --job auto_loop_once; sleep 15; done
```

## Added 2026-10-25 (8h window kickoff)
- 8 concurrent L1 stress: scripts/test_l1_runner_lock_stress.py → STRESS PASS (1 ok + 7 lock_held); see 06_lock_stress.json
- p1_scheduled_runner supports JOB=auto_loop_once
- Automations: 07:00 and 11:00 JST work wakes

