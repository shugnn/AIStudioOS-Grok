# Items that need founder decision (not auto-executable)

Grok track continues engineering without these; **blocked only** where human time or policy is required.

| ID | Decision | Default if silent |
|----|----------|-------------------|
| D1 | Re-run full soak with `--max-wall-seconds 86400` on host | Skip; keep PARTIAL 1330/1440 |
| D2 | Authorize J-Exp-01 implementation (cross-track ACK) | Design only (`docs/j-exp01-cross-track-ack.md`) |
| D3 | Tag release e.g. `p0-isolated-v1` on current main | No tag |
| D4 | ChatGPT must complete peer 24h before next joint claim | Independent tracks; no wait |

Production 7×24 remains **NOT ACCEPTED** regardless of D1–D4.

How to decide: comment on Issue #9 with `APPROVE D1` / `DEFER D1` etc.
