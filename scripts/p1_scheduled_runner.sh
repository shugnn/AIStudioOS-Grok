#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
EVIDENCE_DIR="$ROOT/docs/progress/p1_cron_evidence"
mkdir -p "$EVIDENCE_DIR"
LOG="$EVIDENCE_DIR/scheduler.log"
INTERVAL_SEC="${INTERVAL_SEC:-25}"
JOB="${JOB:-dry_protocol_check}"
RUNS="${RUNS:-3}"

echo "=== P1 local scheduler start $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee "$LOG"
echo "interval_sec=$INTERVAL_SEC runs=$RUNS job=$JOB root=$ROOT" | tee -a "$LOG"

for i in $(seq 1 "$RUNS"); do
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "--- run $i/$RUNS at $TS ---" | tee -a "$LOG"
  set +e
  OUT=$(python3 scripts/l1_runner.py --job auto_loop_once 2>&1)
  RC=$?
  set -e
  echo "exit_code=$RC" | tee -a "$LOG"
  echo "$OUT" | tee -a "$LOG"
  STAMP=$(date -u +%Y%m%d%H%M%S)
  echo "$OUT" > "$EVIDENCE_DIR/run-${i}-${STAMP}.stdout.txt"
  echo "$RC" > "$EVIDENCE_DIR/run-${i}.exitcode"
  LATEST=$(ls -t docs/progress/runner-*.json 2>/dev/null | head -1 || true)
  if [ -n "$LATEST" ]; then
    cp -f "$LATEST" "$EVIDENCE_DIR/run-${i}-$(basename "$LATEST")"
    echo "artifact=$LATEST" | tee -a "$LOG"
  fi
  if [ "$i" -lt "$RUNS" ]; then
    echo "sleep ${INTERVAL_SEC}s until next scheduled fire..." | tee -a "$LOG"
    sleep "$INTERVAL_SEC"
  fi
done

echo "=== P1 local scheduler done $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" | tee -a "$LOG"
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("docs/progress/p1_cron_evidence")
exits = sorted(p.glob("run-*.exitcode"))
print("exit_codes:", [f.read_text().strip() for f in exits])
ids=set(); dups=[]
for f in p.glob("run-*-runner-*.json"):
    try:
        d=json.loads(f.read_text())
        rid=d.get("run_id")
        if rid in ids: dups.append(rid)
        ids.add(rid)
    except Exception as e:
        print("parse err", f, e)
print("unique_run_ids:", len(ids), "dups:", dups)
PY
