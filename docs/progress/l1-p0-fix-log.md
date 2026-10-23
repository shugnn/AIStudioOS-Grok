# L1 Runner P0 fix verification log

**Date**: 2026-10-24  
**Commit**: (see git after push)  
**Review**: ChatGPT conditional on Grok #5

## Commands

```bash
# concurrent lock
python scripts/l1_runner.py --job dry_protocol_check --simulate-hang 4 &
sleep 0.3
python scripts/l1_runner.py --job dry_protocol_check
# expected: second => skipped lock_held

# failure exit code
env -u GH_TOKEN -u GITHUB_TOKEN python scripts/l1_runner.py --job heartbeat
# expected: status failed, exit 1

# kill -9 recovery
python scripts/l1_runner.py --job dry_protocol_check --simulate-hang 20 &
kill -9 $!
python scripts/l1_runner.py --job dry_protocol_check
# expected: status ok
```

## Observed (2026-10-23T17:40Z sandbox)

- concurrent → `skipped` / `lock_held`
- no token heartbeat → `failed`, exit 1
- kill -9 → next run `ok`
