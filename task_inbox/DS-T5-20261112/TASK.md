# 任务单 DS-T5-20261112

| 字段 | 值 |
|------|-----|
| task_id | DS-T5-20261112 |
| 中文名称 | L3 语义修订（必须调用模型） |
| 来源 | Issue #9 评论 [6820308282](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-6820308282)（2026-11-12T09:49:31Z） |
| 接收确认 | Issue #9 评论 6821767846 |
| 目标 | 调用模型解读四条自然语言财务抱怨，据此把 `candidate_v3.json` 修订为 `candidate_v4.json`，再由产品 Verifier 校验 |
| 数据 | 复用 T4 `appts.csv`（PR #20 / `d723cfc`）。冻结校验：含表头 301 行、12350 字节、SHA256 `a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28`。本目录 `data/appts.csv` 已按该指纹核对通过 |
| 待修候选 | `candidate_v3.json`，原文照录任务卡，未改 |
| 交付（付费运行后） | `deliverables/interpretation.json`、`candidate_v4.json`、`model_usage.json`、`verdict.json`、`manifest.json` |
| 约束 | 已按 D-023 在 Ubuntu 上进行一次付费模型调用（上限 ¥5）。抱怨由模型解读，未人工翻译成规则。密钥只在执行机环境中加载，不写入 git 或 Issue。不启动 L2-2（72 小时浸泡），不写 START 登记。不宣称生产 7×24。不宣称 T5、L3 语义修订或观察轨已被验收 |
| 截止 | 任务卡写明确认后 48 小时。创始人确认于 2026-11-13 07:49（亚洲/上海），截止为 2026-11-15 07:49（亚洲/上海） |
| 状态 | SUBMITTED_FOR_OBSERVATION_TRACK_REVIEW |

创始人已于 2026-11-13 07:49（亚洲/上海）在本对话确认「按 D-023 执行 T5」。Worker 已真实调用 DeepSeek（`interpret_complaint`），产品 Verifier 判定 ACCEPTED。这不是观察轨验收，也不宣称生产 7×24，不启动 L2-2 时钟。
