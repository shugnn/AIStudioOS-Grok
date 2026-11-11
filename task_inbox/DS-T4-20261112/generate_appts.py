import random
from datetime import date, timedelta

rng = random.Random(20261112)
start = date(2026, 1, 1)
rows = []
for i in range(1, 301):
    pid = "P%04d" % rng.randrange(1, 201)
    dept = ["med", "surg", "ped", "derm"][rng.randrange(4)]
    vd = start + timedelta(days=rng.randrange(0, 273))
    fee = rng.randrange(2000, 120000)
    st = "completed" if rng.randrange(100) < 80 else ("cancelled" if rng.randrange(2) == 0 else "no_show")
    rows.append((i, pid, dept, vd.isoformat(), fee, st))

csv = "appt_id,patient_id,dept,visit_date,fee_cents,status\n" + "\n".join(",".join(map(str, r)) for r in rows) + "\n"
# write UTF-8, trailing newline, no BOM
