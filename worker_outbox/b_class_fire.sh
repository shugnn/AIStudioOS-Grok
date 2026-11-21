#!/usr/bin/env bash
# One-shot B-class self-check fallback. Idempotent on task_id+scheduled_for_utc.
# Usage: b_class_fire.sh <task_id> <scheduled_for_utc> [dispatch_comment_id]
set -euo pipefail
TASK_ID="${1:?task_id}"
SCHEDULED_FOR_UTC="${2:?scheduled_for_utc}"
DISPATCH_ID="${3:-}"
PROOF="/workspace/worker_outbox/B_CLASS_PROOF.jsonl"
LOG="/workspace/worker_outbox/automation_log.jsonl"
mkdir -p /workspace/worker_outbox
FIRE_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [[ -f "$PROOF" ]] && grep -F "\"task_id\":\"${TASK_ID}\"" "$PROOF" | grep -F "\"scheduled_for_utc\":\"${SCHEDULED_FOR_UTC}\"" | grep -q '"fired_utc":"[0-9]'; then
  echo "already fired for ${TASK_ID} @ ${SCHEDULED_FOR_UTC}"
  exit 0
fi
# This script records the real fire. Issue ACK/INTAKE_FAILURE is left to an awake worker session.
LINE=$(python3 -c "import json,sys; print(json.dumps({
  'task_id': sys.argv[1],
  'scheduled_for_utc': sys.argv[2],
  'fired_utc': sys.argv[3],
  'one_shot': True,
  'cleanup': 'auto',
  'action_taken': 'self_built_fire_recorded',
  'evidence_url': None,
  'dispatch_comment_id': int(sys.argv[4]) if sys.argv[4] else None,
  'note': 'b_class_fire.sh fired; receipt check/push left to awake worker session'
}, ensure_ascii=False, separators=(',',':')))" "$TASK_ID" "$SCHEDULED_FOR_UTC" "$FIRE_UTC" "$DISPATCH_ID")
# replace scheduled-null line if present, else append
if [[ -f "$PROOF" ]] && grep -qF "\"task_id\":\"${TASK_ID}\"" "$PROOF" && grep -qF "\"scheduled_for_utc\":\"${SCHEDULED_FOR_UTC}\"" "$PROOF"; then
  tmp="$(mktemp)"
  python3 -c "
import json,sys
task, sched, newline = sys.argv[1], sys.argv[2], sys.argv[3]
path='${PROOF}'
out=[]
replaced=False
for line in open(path):
    line=line.strip()
    if not line:
        continue
    row=json.loads(line)
    if row.get('task_id')==task and row.get('scheduled_for_utc')==sched and not row.get('fired_utc'):
        out.append(newline)
        replaced=True
    else:
        out.append(line)
if not replaced:
    out.append(newline)
open(path,'w').write('\n'.join(out)+'\n')
" "$TASK_ID" "$SCHEDULED_FOR_UTC" "$LINE"
else
  printf '%s\n' "$LINE" >> "$PROOF"
fi
printf '%s\n' "$(python3 -c "import json,sys; print(json.dumps({
  'ts_utc': sys.argv[1],
  'kind': 'B',
  'round_type': 'B',
  'saw_new_dispatch': False,
  'posted_ack': False,
  'intake_latency_effective_s': None,
  'missed_round': False,
  'note': 'b_class_fire.sh for '+sys.argv[2]
}, ensure_ascii=False, separators=(',',':')))" "$FIRE_UTC" "$TASK_ID")" >> "$LOG"
echo "recorded fire $FIRE_UTC for $TASK_ID"
