# Dual-track P0 matrix (2026-11-07)

**Production 7×24: NOT ACCEPTED on either track.**

| Gate | Grok | ChatGPT |
|------|------|---------|
| OS scheduler ≥3 | PASS (schtasks) | PASS (os-parity-20261027) |
| NEW→VERIFY→ACCEPT | CONDITIONAL | CONDITIONAL |
| Long soak wall 24h | **PASS** Ubuntu aaf8d24 + Windows D1 | formal-16f **FAIL** (monitor-stale); no public 24h PASS |
| Supervision R3 | **PASS** Ubuntu auto-receipt | local remediation; **weak GitHub R6** |
| Evidence on main | metrics + R3 receipt | Runner MVP @ `835fe67`; little since 2026-10-28 |
| Emergency stop | yes | (their tools) |

## Grok highlights

- Ubuntu-24H: wall 86400.001 · final true · with_work 1185/1233
- R3 before long run
- L2-4 incomplete (console/WT). 2026-11-09 host capture is unverified: WT 1000 count 0; scheduler operational log disabled

## ChatGPT (last Grok scan 2026-11-07)

- main still **`835fe67`**
- No new public commits after merge PR #9
- Joint D4: **not recommended** until public supervision receipts + comparable 24h

Cross-review: Grok #9 ↔ ChatGPT #11.
