# 任务单 DS-T2-20261110

| 字段 | 值 |
|------|-----|
| task_id | DS-T2-20261110 |
| 来源 | Issue #9 冻结卡，comment 6761044627，2026-11-10T06:50:13Z |
| 目标 | 在 T1 同一数据集上产出同一结果；J2 完成后、J3 开始前 SIGKILL Worker；由产品入口自行恢复到 DONE |
| 数据 | orders.csv 与 T1 相同：6001 行 / 237705 字节 / SHA256 `633aded091b1da111f4c3c9c378c975d3bdddf17e85a0fd3b001c7e4ddbf7ffe` |
| 交付 | `deliverables/summary.json` / `anomalies.json` / `report.md` / `recovery_report.json` / `manifest.json` |
| 入口 | `PYTHONPATH=. unshare -r -n python3 scripts/worker_run_task.py --task-id DS-T2-20261110` |
| 约束 | 零付费、禁网络、不改对方仓。生产 7×24 **NOT ACCEPTED**。不启动 L2-2，不跑 soak，不登记计划任务 |
| 状态 | EXECUTED_PENDING_INDEPENDENT_REVIEW（执行证据，不是观察轨验收） |

## 冻结卡（DS-T2-20261110）

在 T1 同一数据集上执行同一产出。正常开始后，在 J2（月度汇总）完成、J3（异常清单）开始前，对 Worker 进程发送 SIGKILL。再通过产品入口重启。系统自行判断已完成与未完成并继续到 DONE。不得重复完成，不得损坏。不得手工改交付文件。

作业：

| 作业 | 名称 |
|------|------|
| J1 | generate_or_verify_orders_csv |
| J2 | monthly_summary |
| J3 | anomaly_list |
| J4 | evidence_pack_manifest |

口径与 T1 相同：金额为两位小数字符串；`total_amount` 与分组金额是 amount 列总和，不按 status 轧差；`by_month` 为 2026-01..2026-09；`by_status` 为 paid/pending/refunded/cancelled；`by_channel` 为 web/app/store；`top10_customers` 为 `{customer_id, orders, amount}`；异常每条触发规则一条，按 order_id 再按 rule 排序；A4 窗口 2026-01-01..2026-09-30 含端点；A3 标记每一个 order_id 重复的行。

## 归一化（A-1 / A-4）

- `summary.json` 与 `anomalies.json` 与 T1 密封件字节相同（同一 `json.dumps(indent=2)`）。
- `report.md` 仅把任务号 `DS-T2-20261110` 换成 `DS-T1-20261108` 后，与 T1 `report.md` 字节相同。
- 不改写 summary/anomalies 去凑哈希。`report.md` 保留本任务号，供 A-5 绑定。

## 恢复报告

`idempotency_keys` 只列出「同一 key 被再次提交」的碰撞。每个作业 key `{task_id}:{job_id}` 只提交一次时，该列表为 `[]`。已提交的 key 在 `state/checkpoint.json` 的 journal 里。

## 注入与恢复

1. 执行前写入一次性令牌 `inject/sigkill_at`，内容 `after_J2_before_J3`。
2. 产品在 J2 的检查点 fsync 之后写出 `state/kill_window.json`，删掉令牌，然后停在 J3 之前。
3. 外部对 `kill_window.json` 里的 pid 发送 SIGKILL，并把真实 pid / UTC / signal 9 写入 `state/sigkill_event.json`。该文件不是交付物。
4. 第二次只跑产品入口。产品读检查点，跳过产物哈希仍匹配的 J1/J2，再跑 J3/J4，并自己写出 `recovery_report.json`。

缺 `sigkill_event.json`、pid 不一致、或已提交作业的产物被改过时，产品不把任务报成恢复成功，也不重写已损坏的文件。
