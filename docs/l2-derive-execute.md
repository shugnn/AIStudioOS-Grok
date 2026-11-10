# Derive, then execute

This note is the product path that sits after the Case A / Case B derivation evidence in [`l2-derivation-evidence.md`](l2-derivation-evidence.md). Those evidence files are unchanged. Observation-track comment 6767990189 on Issue #9 accepted that derivation as the right capability and left L2 (self-decompose / self-implement) CONDITIONAL, pending one later end-to-end observation. This repository does not contain that observation card. This run is not that card.

**L2 remains CONDITIONAL. It is not granted and not accepted.**

**Production 7×24 is NOT ACCEPTED.**

**The L2-2 72h clock is NOT STARTED.** Comment 6761044915 is not a start.

This is not a T3 run. T1 (`DS-T1-20261108`) and T2 (`DS-T2-20261110`) were not rerun. Their dispatch files and deliverables were not rewritten. No `task_inbox/DS-T3-*` card was added.

## What the worker does

`scripts/worker_run_task.py` reads a goal statement, a column schema, and an input CSV. It calls `TaskDecomposer.decompose()`. That call still ignores task id and fixture name. The derived jobs are executed from each job's `kind` and structured `inputs` (key, columns, grain, measures, time column, SLA start/end, aging open/close). Titles are not a dispatch table.

The derived job list is written to `derived_dispatch.json` in the output directory after derivation. That file is a product output. The runner does not read it, and it does not read a pre-written `dispatch.json`, to decide which jobs to run. It does not import `worker_jobs.py`.

Job deliverables are written beside the dispatch. The `evidence_pack` job records sha256 and byte length of the input CSV and of the other job files. The dispatch then records the evidence file's hash. Checksums are computed from the bytes just written. They are not copied from a frozen observation fingerprint.

`DS-T1-20261108` and `DS-T2-20261110` are refused before any read or write, including when a goal file is later placed in those inboxes. That refusal is write-protection. It is not a table that selects jobs.

## Local fixture

`fixtures/local_support_tickets_demo/` is a product-side demo. It is not an observation-track card. The statement asks for a monthly and weekly labor-amount summary by priority, an anomaly list, an SLA breach list by priority, weekly backlog aging, and an evidence pack. The columns are `ticket_id`, `opened_at`, `first_response_at`, `resolved_at`, `priority`, `status`, and `labor_amount`. The ten data rows were written in this repository. There is no `dispatch.json` and no `worker_jobs.py` in that directory.

```bash
PYTHONPATH=. python scripts/worker_run_task.py \
  --card fixtures/local_support_tickets_demo \
  --out /tmp/local-support-tickets-demo
```

The historical orders titles (`generate_or_verify_orders_csv`, `monthly_summary`, `anomaly_list`, `evidence_pack_manifest`) are not the job list for this fixture. Those strings were written on the T1 and T2 cards. This path does not look them up.

## Execution rules

The closed rules live in `control_plane/derived_worker.py`. Short form:

| Kind | How it runs |
|------|-------------|
| `verify_input_schema` | Header must equal `inputs.columns` in order. `inputs.key`, when set, must be non-blank and unique. sha256 and byte length come from the input file. |
| `temporal_aggregate` | Bucket `inputs.time_column` by `inputs.grain`. Sum `inputs.measures` as decimals. `inputs.group_by` is the extra key when it is not null. Unparseable times are skipped. Unparseable measures are counted and are not added as zero. |
| `anomaly_list` | On `inputs.columns`: blank is `missing`. A column that is at least 80% decimal is numeric. On a numeric column: unparseable is `non_numeric`, value < 0 is `negative`, and value > median + 3 * MAD is `high_outlier` when at least four numbers parse and MAD is not 0. |
| `sla_breach_list` | No duration threshold. First match on `inputs.start` / `inputs.end`: missing or bad start, missing end, bad end, or end before start. Counts use `inputs.group_by`. |
| `backlog_aging` | `as_of` is the latest parsed timestamp in `inputs.open` and `inputs.close`, not the wall clock. Blank close stays open and is aged to `as_of`. Buckets use `inputs.grain` of the open time. |
| `evidence_pack` | Hash the input and the other job files named by the run. The pack does not hash itself, `derived_dispatch.json`, or `worklog.json`. |

A failed `verify_input_schema` does not run the later analytical jobs. The derived list is still written, with those jobs marked skipped. The evidence pack still records what was written.

No rule matches → the derived list is empty, the run is not successful, and no historical four-job list is substituted.
