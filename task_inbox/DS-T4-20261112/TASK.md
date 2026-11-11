# 任务单 DS-T4-20261112

| 字段 | 值 |
|------|-----|
| task_id | DS-T4-20261112 |
| 来源 | Issue #9 评论 6802795658（2026-11-11T17:33:23Z）；生成脚本补件 6804688982；字节更正 6804695605 |
| 目标 | 用产品 Verifier 判定候选 v1 为 REJECTED，逐条列出违反的合同规则；Worker 据此修订出 v2；同一 Verifier 再判定 ACCEPTED |
| 数据 | `generate_appts.py` 为观察轨补件脚本。`data/appts.csv` 由该脚本写出。冻结校验：300 条数据、含表头 301 行、12350 字节、SHA256 `a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28` |
| 候选 v1 | `candidate_v1.json`，任务卡原文，故意不合格 |
| 合同 | R1 金额为两位小数字符串，不得为浮点数；R2 `by_dept` 含 med/surg/ped/derm（计数为 0 也要出现）；R3 `by_month` 键按月份升序；R4 仅 `status=completed` 计入计数与营收 |
| 交付 | `deliverables/verdict_v1.json`、`candidate_v2.json`、`verdict_v2.json`、`revision_log.json`。`cost.json` 本轮是 BLOCKED 记录，不是已完成的付费调用 |
| 约束 | 本轮不调用付费模型 API，不使用密钥，不联网。Worker 与 Verifier 分进程。不启动 L2-2，不写 START 登记。不宣称生产 7×24。不宣称 L3、T4 或观察轨已被验收 |
| 截止 | 任务卡写明确认后 48 小时。本文件不登记 L2-2 时钟 |
| 状态 | SUBMITTED_FOR_OBSERVATION_TRACK_REVIEW |

v2 的计数和金额不在本任务单里预写。Worker 必须从 `appts.csv` 按冻结合同重算。`verdict_v2` 里的 ACCEPTED 只是产品 Verifier 对候选 v2 的合同判定，不是观察轨验收。
