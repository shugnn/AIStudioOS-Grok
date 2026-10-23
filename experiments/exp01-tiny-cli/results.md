# Exp-01 Results — ScriptManager Baseline

**Date**: 2026-10-23  
**Manager type**: `script_manager` (deterministic — NOT LLM)  
**Commit**: (see git after push)

## Summary

| Metric | Result |
|--------|--------|
| Goal complete | **Yes** |
| Accepted tasks | scaffold, implement core, add tests, verify acceptance |
| Idempotency | Pass |
| Budget hard-block ($999 est) | Pass |
| Recovery after reload | Pass (4 accepted retained) |
| Human interventions | **0** |
| New paid spend | **$0** |
| pytest | Pass (6 tests) |
| Permission deny network/git_push | Pass |

## How to reproduce

```bash
cd AIStudioOS-Grok
rm -f experiments/exp01-tiny-cli/cp_state.json experiments/exp01-tiny-cli/cp_state.bak
rm -rf experiments/exp01-tiny-cli/workspace/wcmini experiments/exp01-tiny-cli/workspace/test_wcmini.py
PYTHONPATH=. python experiments/exp01-tiny-cli/run_exp01.py
```

## Artifacts

- `experiments/exp01-tiny-cli/run_exp01.py` — ScriptManager + Worker + Independent Verifier
- `experiments/exp01-tiny-cli/logs/run.log`
- `experiments/exp01-tiny-cli/logs/pytest_*.txt`
- `experiments/exp01-tiny-cli/results.json`
- `experiments/exp01-tiny-cli/workspace/wcmini/` — deliverable CLI

## Notes

- Path allowlist matching fixed for absolute paths under `experiments/`
- Fixture word count corrected (7 words)
- Zero LLM / zero external API cost
