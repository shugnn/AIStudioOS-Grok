# Emergency stop (file kill switch)

**Not** a production HA controller — local, zero-cost, human-operated.

## Arm

```powershell
cd "D:\work\AIStudioOS项目-Grok"
Set-Content -Path docs\progress\EMERGENCY_STOP -Value "founder stop $(Get-Date -Format o)"
```

Effects:
- `scripts/l1_runner.py` exits **3** with `status=emergency_stop` (no new jobs)
- Soak should be stopped by user (Ctrl+C) or will fail via-l1 cycles with exit 3

## Clear

```powershell
Remove-Item docs\progress\EMERGENCY_STOP -ErrorAction SilentlyContinue
```

Do **not** commit `EMERGENCY_STOP` itself (runtime only). This doc is the procedure.

## Exit codes (L1)

| Code | Meaning |
|------|---------|
| 0 | ok |
| 1 | job failed |
| 2 | lock_held skip |
| 3 | emergency stop |
