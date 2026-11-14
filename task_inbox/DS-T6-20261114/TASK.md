# 任务单 DS-T6-20261114

| 字段 | 值 |
|------|-----|
| task_id | DS-T6-20261114 |
| 中文名称 | L4 有界自我迭代 |
| 来源 | Issue #9 评论 [6869202295](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-6869202295)（2026-11-14T01:16:40Z） |
| 接收确认 | Issue #9 评论 [6872806848](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-6872806848)（2026-11-14 14:04 亚洲/上海） |
| 目标 | 从官方 `candidate_v0`（1/5，仅 R3 通过）起，由模型逐轮只修一项不合格项，迭代到 5/5 或触发停止条件 |
| 数据 | 复用 T4/T5 `appts.csv`。冻结校验：含表头 301 行、12350 字节、SHA256 `a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28`。本目录 `data/appts.csv` 已按该指纹核对通过 |
| 起始候选 | `candidate_v0.json`，原文照录任务卡，未改 |
| 交付（付费运行后） | `deliverables/iterations.jsonl`、`final_candidate.json`、`stop_report.json`、`verifier_final.json` |
| 约束 | 已按 D-023 在 Ubuntu 上付费运行（总费用上限 ¥5）。每一轮必须真实调用模型，禁止把规则手写进脚本绕过模型。密钥只在执行机环境中加载，不写入 git 或 Issue。不启动 L2-2（72 小时浸泡），不写 START 登记。不宣称生产 7×24。不宣称 T6、L4 或观察轨已被验收。不合并 PR #19、#20、#21，不重跑 T1–T5 |
| 截止 | 任务卡写明确认后 72 小时。创始人确认于 2026-11-14 14:03（亚洲/上海），截止为 2026-11-17 14:03（亚洲/上海） |
| 状态 | SUBMITTED_FOR_OBSERVATION_TRACK_REVIEW |

创始人已于 2026-11-14 14:03（亚洲/上海）在本对话确认「按 D-023 执行 T6」。Worker 已于 2026-11-14 22:47:59–22:48:04（亚洲/上海）真实调用 deepseek-flash 四轮，产品 Verifier 记分 5/5，stop_reason=SCORE_5。这不是观察轨验收，也不宣称生产 7×24，不启动 L2-2 时钟。
