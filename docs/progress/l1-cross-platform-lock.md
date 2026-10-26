# L1 cross-platform lock (Windows + POSIX)

**Date**: 2026-10-25  
**Change**: `scripts/l1_runner.py` OSFileLock now selects backend by platform.

| Platform | Backend | Acquire | Release on process death |
|----------|---------|---------|--------------------------|
| Linux/macOS | `fcntl.flock(LOCK_EX\|LOCK_NB)` | non-blocking | yes (kernel) |
| Windows | `msvcrt.locking(LK_NBLCK, 1)` | non-blocking | yes (CRT closes fd) |

## Tests (Linux sandbox)

```
python3 scripts/test_l1_runner_lock.py      # ALL PASS
python3 scripts/test_l1_runner_lock_stress.py  # STRESS PASS
```

Windows validation: run the same two scripts on founder PC after pull; then optional
`py -3 scripts/soak_2h.py --cycles 5 --interval 5 --via-l1`.

## Not claimed

- System service / Task Scheduler install (needs explicit founder action)
- Production 7×24 autonomy
