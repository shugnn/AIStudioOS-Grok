# DS-T3-20261111

Received from the observation track, Issue #9 comment 6775337980 (2026-11-10T18:11:16Z). Founder approval 2026-11-11. Deadline is 72 hours after that confirmation. This folder is the published card: the goal, the schema, and the generated input. It does not contain a job list.

| Field | Value |
| --- | --- |
| task_id | DS-T3-20261111 |
| goal | 为图书馆借阅数据生成「借阅运营汇总 + 逾期清单 + 可独立核验的证据包」。 |
| input | loans.csv |
| reference_date | 2026-10-31 |
| freeze | 4001 lines including header; 165090 bytes; SHA256 `429b3287c37d07c350926e53bacc0f475f77dabd94dc1eb3bc1f703776ffdf51` |

Overdue means not returned and (2026-10-31 − borrowed_date) in days is greater than loan_days. How to split the work is not written here. `scripts/worker_run_task.py` calls `TaskDecomposer.decompose()` and does not read a `dispatch.json`.

This is a T3 run submitted for observation-track acceptance. Observation-track acceptance is not claimed. L2 is not granted and not accepted. Production 7×24 is NOT ACCEPTED. The L2-2 72h clock is NOT STARTED. Comment 6761044915 is not a start.

The published generator is quoted so the csv can be checked. The worker does not execute this quote. It reads `loans.csv`.

```python
import random
from datetime import date, timedelta
rng = random.Random(20261111); start = date(2026,1,1); rows=[]
for i in range(1,4001):
    book="B%03d"%rng.randrange(1,301); member="M%04d"%rng.randrange(1,501)
    bd=start+timedelta(days=rng.randrange(0,273)); days=[14,21,30][rng.randrange(3)]
    cat=["lit","sci","tech","hist"][rng.randrange(4)]
    u=rng.randrange(100)
    rd="" if u>=60 else (bd+timedelta(days=rng.randrange(0,days+15))).isoformat()
    rows.append((i,book,member,bd.isoformat(),days,rd,cat))
csv="loan_id,book_id,member_id,borrowed_date,loan_days,returned_date,category\n"+"\n".join(",".join(map(str,r)) for r in rows)+"\n"
```
