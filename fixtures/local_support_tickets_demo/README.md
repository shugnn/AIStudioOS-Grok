# Local demo input — not an observation card

This directory is a product-side fixture for the derive → execute → deliver path.
It is not an observation-track task. It is not `DS-T1-20261108`, `DS-T2-20261110`, or a `DS-T3` card.
Nothing here was downloaded. The ten ticket rows were written in-repo.

`goal.json` holds a goal statement and a column schema. `data/tickets.csv` is the input table.
There is no `dispatch.json` and no `worker_jobs.py`. A run derives the job list with
`TaskDecomposer.decompose()`, executes those jobs, and writes `derived_dispatch.json` into the
output directory. That dispatch is an output.

```bash
PYTHONPATH=. python scripts/worker_run_task.py \
  --card fixtures/local_support_tickets_demo \
  --out /tmp/local-support-tickets-demo
```

L2 remains CONDITIONAL. It is not granted and not accepted.
Production 7×24 is NOT ACCEPTED. The L2-2 72h clock is NOT STARTED.
This fixture is not a T3 run.
