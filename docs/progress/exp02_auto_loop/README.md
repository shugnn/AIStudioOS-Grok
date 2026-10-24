# Exp-02 / Exp-02b — continuous auto-execution loop

## exp02 (script-only)
`auto_loop.py` — in-memory Manager→Worker→Verifier, 4/4 verified.

## exp02b (Control Plane–driven)
`cp_driven_loop.py` — same jobs under real Control Plane state machine:

propose → approve → running → verifying → accepted|rejected

- State file default: `/tmp/aistudio_exp02b/cp_state.json` (sandbox FS stability)
- Snapshot for repo: `cp_state.snapshot.json`
- L1 wake job: `python scripts/l1_runner.py --job auto_loop_once`

### Reproduce
```bash
python3 experiments/exp02_auto_loop/cp_driven_loop.py --reset --max-steps 10
python3 scripts/l1_runner.py --job auto_loop_once   # after partial seed
```
