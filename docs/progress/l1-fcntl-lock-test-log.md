# L1 fcntl OS-lock verification

**Date**: 2026-10-24

## Results

| Test | Expected | Observed |
|------|----------|----------|
| Concurrent second runner | skipped / lock_held | PASS |
| kill -9 holder then re-run | next acquires, status ok | PASS |
| heartbeat without token | status failed, exit 1 | PASS |

## Commands

```bash
python scripts/l1_runner.py --job dry_protocol_check --simulate-hang 3 &
sleep 0.4
python scripts/l1_runner.py --job dry_protocol_check

python scripts/l1_runner.py --job dry_protocol_check --simulate-hang 30 &
kill -9 $!
python scripts/l1_runner.py --job dry_protocol_check

env -u GH_TOKEN -u GITHUB_TOKEN python scripts/l1_runner.py --job heartbeat
```
