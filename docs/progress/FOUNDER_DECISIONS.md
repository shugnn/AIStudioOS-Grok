# Founder decisions

## Closed / resolved

| ID | Decision | Result |
|----|----------|--------|
| D1 | Full-window 24h re-run | **PASS** wall 86400s; 1142 cycles; with_work 1100 (afe25c2) |

## Open (L2 — approach 7×24, not claim)

See `docs/progress/L2_NEXT_TIER.md`.

| ID | Decision | Default if silent |
|----|----------|-------------------|
| D2 | Implement J-Exp-01 | Design only |
| D3 | Tag `p0-isolated-v1` | No tag |
| D4 | Wait for ChatGPT 24h before joint claim | Independent |
| **L2-4** | 1-day logon schtasks duty + stall_watchdog | Not registered |
| **L2-2** | 72h wall soak | Not started |
| **L2-3** | One mid-run kill recovery drill | Not done |
| **L2-5** | Boot-time task (admin) | **Denied by default** |
| **L2-6** | Change power/sleep settings | **Denied by default** |

Comment on Issue #9: `APPROVE L2-4` / `APPROVE L2-2` / `DEFER …`

Production 7×24 remains **NOT ACCEPTED** until a separate program clears L2-5/6-class gates and multi-day evidence.
