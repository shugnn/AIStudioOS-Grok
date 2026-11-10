# DS-T3-20261111

`DS-T3-20261111` is submitted for observation-track acceptance. This is a T3 run submitted for observation-track acceptance. Observation-track acceptance is not claimed. claim_boundary.t3_run stays false on every run, including this one. That constant does not grant or accept the submission.

L2 is not granted and not accepted.

Production 7×24 is NOT ACCEPTED.

The L2-2 72h clock is NOT STARTED. Comment 6761044915 is not a start.

## Goal

为图书馆借阅数据生成「借阅运营汇总 + 逾期清单 + 可独立核验的证据包」。

## Why this split

语句里有证据、逾期、汇总，列角色决定哪些规则成立，所以拆成 verify_input_schema、loan_operations_summary、overdue_list、evidence_pack，不按任务编号套固定清单。

## Alternatives considered

- 不按月或按周加总金额：语句有汇总，但没有月度或周度词。
- 不单列异常：语句没有异常意图。
- 不列时效违约：语句没有时效或违约意图，或没有成对的事件时间列。
- 不做账龄：语句没有积压或账龄意图，或没有事件时间列。

## Derived tasks

- `J1` 校验表头和主键 loan_id，并记录输入文件的 sha256 与字节数。 outputs: J1_verify_input_schema.json.
- `J2` 统计笔数、已还、未还和逾期，按 category 与 borrowed_date 的月份汇总，并列出 member_id 的前 10。 outputs: summary.json.
- `J3` 列出 returned_date 为空、且（2026-10-31 − borrowed_date）的天数大于 loan_days 的 loan_id。 outputs: overdue.json.
- `J4` 记录输入和各任务产物的 sha256 与字节数，形成可独立核验的证据包。 outputs: J4_evidence_pack.json, report.md, manifest.json.

## Rules used for the numbers

A loan is returned when the return-date cell is non-blank. Outstanding means that cell is blank. A populated return date is not reinterpreted against the reference date.

Overdue means outstanding and (reference date − borrowed date) in whole days is greater than loan days. Equal to the loan days is not overdue. The reference date is the `reference_date` on the derived job, not a date built into the executor.

Category counts and month counts include every loan. The month is the borrow date's `YYYY-MM`. The top members are ranked by loan count descending, then member id ascending.

## Results

- total_loans: 4000
- total_returned: 2409
- total_outstanding: 1591
- total_overdue: 1591
- by_category: {"hist": 1002, "lit": 997, "sci": 969, "tech": 1032}
- by_month: {"2026-01": 421, "2026-02": 380, "2026-03": 437, "2026-04": 439, "2026-05": 463, "2026-06": 465, "2026-07": 486, "2026-08": 449, "2026-09": 460}
- top10_members: [{"member_id": "M0365", "loans": 17}, {"member_id": "M0110", "loans": 16}, {"member_id": "M0124", "loans": 16}, {"member_id": "M0172", "loans": 16}, {"member_id": "M0425", "loans": 16}, {"member_id": "M0091", "loans": 15}, {"member_id": "M0113", "loans": 15}, {"member_id": "M0119", "loans": 15}, {"member_id": "M0145", "loans": 15}, {"member_id": "M0189", "loans": 15}]
- overdue items: 1591

## Input

Input `loans.csv` sha256 `429b3287c37d07c350926e53bacc0f475f77dabd94dc1eb3bc1f703776ffdf51`, 165090 bytes, 4001 lines.

## Derivation

Jobs were produced by `TaskDecomposer.decompose()`. `plan.json` is a projection of those jobs. `derived_dispatch.json` was written after derivation and was not read as an input. No pre-written `dispatch.json` was read. `worker_jobs.py` was not imported.
