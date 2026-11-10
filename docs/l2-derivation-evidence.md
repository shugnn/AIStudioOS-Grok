# L2 derivation evidence

This note is the minimal evidence asked after observation-track (DS) judged L2 conditional on Issue #9 comment 6765608469 (2026-11-10T11:00:40Z). DS asked for one demonstration that a different goal produces a different task set, and wrote that a templated split is a script, not decomposition. The quoted ask: 「请给一次「换目标后拆出的任务不同」的最小证据（例如换一份不同结构的输入，说明你如何决定任务集）」and 「模板化的拆活不是拆活，是脚本」.

**L2 is not granted and not accepted.** This file does not record an observation-track acceptance. DS has not accepted this evidence.

**Production 7×24 is NOT ACCEPTED.**

**The L2-2 72h clock is NOT STARTED.** Comment 6761044915 is not treated as a start. No founder start condition is filled in here.

This is not a new frozen observation task. T1 and T2 were not rerun. `scripts/worker_run_task.py` was not changed and was not used to produce these jobs.

Machine-readable copy of the same runs: [`l2-derivation-evidence.json`](l2-derivation-evidence.json). A test loads that file and checks it against a live call, so the jobs below are the decomposer’s output rather than a hand-written list that the code does not return.

## What T1 and T2 actually did

On main, before this change, `control_plane/task_decomposer.py` `decompose()` returned [] for every input. That stub landed in `0ca8074` and was still the body at `a081c2e`. The same stub is on branch `cursor/ds-t2-20261110-recovery-aae0`.

The dispatch files nevertheless list the same four titles:

| Job | Title written on the card |
|-----|---------------------------|
| J1 | `generate_or_verify_orders_csv` |
| J2 | `monthly_summary` |
| J3 | `anomaly_list` |
| J4 | `evidence_pack_manifest` |

- T1: `task_inbox/DS-T1-20261108/dispatch.json` on main.
- T2: `task_inbox/DS-T2-20261110/dispatch.json` on `cursor/ds-t2-20261110-recovery-aae0`.

Those titles match the shared frozen `orders.csv` card (monthly operating summary, anomaly list, evidence pack). They were written on the dispatch files. `decompose()` did not derive them. This change does not edit those files and does not claim the stub already produced J1–J4.

The jobs derived below are also not those four strings. Matching the old titles on purpose would have been another template.

## How the task set is decided

`TaskDecomposer.decompose(goal)` reads only:

- the statement (`statement`, or else `text` / `title` / `description` / `goal`)
- the columns (`schema.columns`, or else top-level `columns`), each a name or `{name, type}`

It does not read a task id, a fixture name, or `schema.name`. Two calls with the same statement tokens and the same columns return the same jobs. No predicate matches → `[]`.

1. Tokenize the statement on ASCII words (`[a-z0-9_]+`, lowercased). Map those tokens onto a closed intent set: `monthly`, `weekly`, `summary`, `anomaly`, `evidence`, `sla`, `aging`, `verify_input`. The whole sentence is never used as a lookup key.
2. Classify each column. First match wins: `*_id` → identifier; `*_at` → event time; `*_date` / `*_day` / `date` → calendar date; a known measure name (`amount`, `revenue`, …) → measure; `status` / `state` → status; `priority` / `severity` → priority; a declared numeric type → measure; otherwise dimension.
3. Emit a job only when its predicate is true. The title is built from the grain and the column names that satisfied the predicate. There is no stored list of titles to return.
4. Emission order assigns `J1`…`Jn`: verify, month aggregate, week aggregate, anomaly list, SLA breach list, backlog aging, evidence pack.

| Job kind | Fires when |
|----------|------------|
| `verify_input_schema` | The statement asks to verify a frozen input, or asks for evidence, and a schema is present. Key = first identifier column. |
| `temporal_aggregate` | A summary is requested at month and/or week grain, and the schema has a measure and a time column. A calendar date is preferred over an event time. Measures stay in schema order. One job per grain. |
| `anomaly_list` | Anomalies are requested, and a status column or a measure exists. |
| `sla_breach_list` | A breach is requested, at least two event-time columns exist, and a group column is named with `by <column>` or a priority-role column exists. |
| `backlog_aging` | Aging or backlog is requested, and an event-time column exists. Weekly grain wins over monthly when both are present. |
| `evidence_pack` | Evidence is requested and a schema is present. The title is the sorted set of column roles. `inputs.covers` lists the earlier job ids. |

Among several event-time columns, start/open prefers `opened_at`, then `created_at`, otherwise schema order. An SLA end prefers `first_response_at`, `responded_at`, `resolved_at`, `closed_at`, otherwise another event time. An aging close prefers `resolved_at`, then `closed_at`, and does not treat a response timestamp as the close. Those names are a tie-break inside the event-time role. They are not a table of task ids. An unseen set of names (`created_at`, `responded_at`, `closed_at`, `tier`) still composes its own titles; the tests lock that.

Both concrete cases below happen to emit four jobs. That length is not fixed. A statement that is only `monthly summary` emits one job. Dropping the anomaly intent from Case A emits three. Swapping the goal onto the other schema emits two, and the missing predicates stay missing.

## Case A — orders-shaped table, T1-like goal

Statement: “Frozen tabular orders: produce a monthly operating summary, an anomaly list, and an independently verifiable evidence pack.”

Columns, in order: `order_id`, `order_date`, `amount`, `status`, `customer_id`, `channel`.

| Job | Title | Why |
|-----|-------|-----|
| J1 | `verify_input_schema_keyed_by_order_id` | `frozen` and `verifiable`/`evidence`; first identifier is `order_id` |
| J2 | `aggregate_amount_by_month_of_order_date` | `monthly` + `summary`; measure `amount`; calendar date `order_date` |
| J3 | `list_anomalies_on_status_amount` | `anomaly`; status `status` and measure `amount` |
| J4 | `assemble_evidence_pack_over_calendar_date_dimension_identifier_measure_status` | evidence requested; roles are calendar_date, dimension (`channel`), identifier, measure, status; covers J1–J3 |

`customer_id` stays an identifier, so it is not aggregated and not listed as an anomaly column.

## Case B — tickets, different goal

Statement: “Support tickets: SLA breach list by priority, weekly backlog aging, and an independently verifiable evidence pack.”

Columns, in order: `ticket_id`, `opened_at`, `first_response_at`, `resolved_at`, `priority`.

| Job | Title | Why |
|-----|-------|-----|
| J1 | `verify_input_schema_keyed_by_ticket_id` | evidence requested; first identifier is `ticket_id`. There is no `frozen` token, so the reason cites evidence only. |
| J2 | `list_sla_breaches_by_priority_from_opened_at_to_first_response_at` | `sla`/`breach`; `by priority` names the priority column; two event times, and the end preference picks `first_response_at` rather than `resolved_at` |
| J3 | `age_backlog_by_week_of_opened_at_until_resolved_at` | `weekly` + `backlog`/`aging`; open `opened_at`; close `resolved_at` |
| J4 | `assemble_evidence_pack_over_event_time_identifier_priority` | evidence requested; roles are event_time, identifier, priority; covers J1–J3 |

The title set is disjoint from Case A. The computed kinds are different predicates (`sla_breach_list`, `backlog_aging`), not renames of `monthly_summary` and `anomaly_list`. Both goals ask for an evidence pack, so both still emit a verify job and an evidence job; those titles still embed the schema (the key column, and the role set).

## Swapped inputs

Same rules, inputs crossed. This is the check that the two results are not two stored answers.

- Case B’s statement on Case A’s columns emits only `verify_input_schema_keyed_by_order_id` and the orders evidence-pack title. The orders schema has no pair of event-time columns, so the SLA list and the backlog aging job do not fire, even though the statement asks for them.
- Case A’s statement on Case B’s columns emits only `verify_input_schema_keyed_by_ticket_id` and the ticket evidence-pack title. The ticket schema has no measure and no status column, so the monthly aggregate and the anomaly list do not fire.

## Limits, stated plainly

- The intent list is a closed ASCII vocabulary. A Chinese-only statement such as 「月度经营汇总、异常清单和证据包」tokenizes to nothing and returns `[]`. That is fail-closed, not a successful parse of the Chinese goal.
- `state` is classified as status. A geographic `state` column would be treated as a status. Case A uses `status`, not `state`.
- Unknown numeric measures need a declared type (`weight` as `float` becomes a measure). An unknown categorical such as `tier` stays a dimension; `by tier` still works for an SLA group because the group is the named column, not a row in a fixture table.
- These jobs are proposals (`status: PENDING`). Nothing here computed a summary, an SLA list, or an evidence pack.
- Historical T1/T2 dispatch titles remain the ones written on those cards. They are not regenerated by this decomposer, and they are not rewritten to look as if they had been.
