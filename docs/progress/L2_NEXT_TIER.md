# L2 — Approach production 7×24 (not claim it)

**L1 (done-ish):** isolated loop, OS trigger, honest metrics, wall-clock 24h D1 PASS, emergency stop.

**L2 goal:** multi-day *bounded* duty-cycle on one host with stall detection and documented recovery — still **non-production**.

## Gate table

| ID | Gate | How to pass | Needs founder host action |
|----|------|-------------|---------------------------|
| L2-1 | Stall detection | `scripts/stall_watchdog.py` sees no new summary row for N minutes → exit non-zero / write alert file | Optional scheduled run |
| L2-2 | 72h wall observation | soak `--max-wall-seconds 259200` + final metrics | **Yes** — leave machine up ~3 days |
| L2-3 | Mid-run kill recovery | kill python mid-soak; restart soak `--no-reset-seed`; metrics continuous | Yes — one fault injection |
| L2-4 | Logon schtasks ≥24h | Task runs after unlock; ≥20 wakes logged | Yes — Register-ScheduledTask |
| L2-5 | Boot/service autostart | Task at startup without interactive logon | **Yes + admin** — explicit approve |
| L2-6 | Power/sleep policy | No silent sleep killing duty cycle | **Yes** — power settings; do not change without approve |
| L2-7 | Independent verifier | `verify_soak_metrics.py` on final pack | No |
| L2-8 | Evidence pack | metrics + summary + SHA256SUMS + Issue #9 | push from host |

Production 7×24 still requires L2-5/6 class controls + multi-host or external monitor + real workload — **out of scope until separate FOUNDER program**.

## Suggested sequence

1. Code: stall watchdog (this commit) — no approve needed to *have* the tool  
2. `APPROVE L2-4` short schtasks duty (1 day)  
3. `APPROVE L2-2` 72h if 1 day stable  
4. Only then discuss L2-5/6
