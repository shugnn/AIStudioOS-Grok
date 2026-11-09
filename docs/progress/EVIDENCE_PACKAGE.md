# Evidence package layout (Grok track)

Standard directories and files for dual-track review. Zero paid. No production claim.

## Binding strength

| Level | Required |
|-------|----------|
| weak | Screenshots / chat only |
| medium | `git` SHA + paths in Issue |
| medium–strong | + `SHA256SUMS.json` via `scripts/evidence_sha256sums.py` |
| strong | SUMS + fixed file list + independent reconcile of artifacts |

## Soak (`docs/progress/soak_2h/`)

| File | Role |
|------|------|
| `metrics.json` | **Required.** `cycles_exit0`, `cycles_with_work`, `cycles_idle`, `sha_full`, `idle_policy` |
| `summary.jsonl` | Per-cycle rows (`with_work`, `idle`, `steps_this_wake`) |
| `soak.log` | Human-readable stream |
| `SHA256SUMS.json` | Optional upgrade to medium–strong |

**Never** report business PASS from `cycles_exit0` alone.

## L1 / scheduler

| Path | Role |
|------|------|
| `docs/progress/runner-*.json` | Per L1 wake artifact (`lock`, `platform`, jobs) |
| `docs/progress/.l1_runner.lock` | Runtime only (gitignored) |

OS scheduler: keep `Get-ScheduledTaskInfo` + ≥3 runner JSON timestamps in Issue #9.

## Control Plane exp state

| Path | Role |
|------|------|
| `docs/progress/exp02_auto_loop/state/` | Live `cp_state.json` / `goal_id.txt` (**gitignored** except `.gitkeep`) |
| `docs/progress/exp02_auto_loop/exp02b-*.json` | Run reports (committable) |
| `docs/progress/exp03_crash_recovery/` | Crash recovery evidence |
| `docs/progress/exp04_cancel_stress/` | Cancel + long queue |

## L2-4 WT correlation + reboot

Gate stays **INCOMPLETE**. Do not file synthetic fixtures as the 2026-11-04 host incident.

| Path | Role |
|------|------|
| `docs/progress/l2_4/SCHEMA.json` | Capture/report ids and the strength rule |
| `docs/progress/l2_4/README.md` | Founder checklist. Done vs still host-gated |
| `tests/fixtures/l2_4/scaffold_*.json` | Synthetic. `evidence_class=scaffold`, `synthetic=true` |
| `docs/progress/l2_4/host/capture.json` | **Absent** until the founder runs the capture script |
| `docs/progress/l2_4/host/report.json` | Correlator output for that capture. Status remains `INCOMPLETE` |
| `docs/progress/l2_4/host/SHA256SUMS.json` | `scripts/evidence_sha256sums.py` after a real capture |

A host report is medium evidence only after the JSON files and hashes are on the branch. It is not a duty-cycle PASS and not production acceptance. `can_close_l2_4` is always false in this scorer.

## Commands

```powershell
py -3 scripts/soak_2h.py --cycles 10 --interval 2 --via-l1 --idle-policy stop
py -3 scripts/evidence_sha256sums.py docs/progress/soak_2h
```

L2-4 scaffold (any OS; not a host log):

```bash
PYTHONPATH=. python -m pytest tests/test_l2_4_correlate.py -q
PYTHONPATH=. python scripts/l2_4_correlate.py \
  --capture tests/fixtures/l2_4/scaffold_strong_time_overlap.json
```

L2-4 host capture (founder Windows only; read-only; does not register tasks):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\l2_4_capture_host.ps1 `
  -OutDir .\docs\progress\l2_4\host `
  -Since "2026-11-03T00:00:00Z" `
  -Until "2026-11-06T00:00:00Z"
py -3 scripts\l2_4_correlate.py --capture docs\progress\l2_4\host\capture.json --out docs\progress\l2_4\host\report.json
py -3 scripts\evidence_sha256sums.py docs\progress\l2_4\host
```

## Dual-track note

ChatGPT evidence lives under their `docs/evidence/`. Cross-review on their Issue #11 / PR history; do not copy their files into this repo.
