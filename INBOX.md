# 工人取件通道（INBOX）

仓库：https://github.com/shugnn/AIStudioOS-Grok  
文档日期：2026-11-21（亚洲/上海）  
依据：[Issue #9 comment 7044085120](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7044085120)（协议 v1）、[comment 7044312076](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7044312076)（地址与命名最终口径）、[comment 7054705152](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7054705152)（观察轨受理 INBOX.md，并修正协议 §六判据）、创始人 2026-11-21 00:23（亚洲/上海）正式确认。  
本文件取代 2026-11-20 版。旧版中的 `task_inbox` 入站口说法、私聊转贴兜底、工作日 09:00–19:00 时窗，全部作废。2026-11-21 11:00 档起，验收主判据以 7054705152 为准（见第 6、9 节）。

## 1. 时窗

- 09:00–23:00（亚洲/上海），每日（含周末）每 2 小时一轮，整点：09/11/13/15/17/19/21/23。
- 允许 ±15 分钟抖动；抖动耗时计入 `intake_latency_effective_s`（该值为观测值，须如实上报）。
- 夜间 00:00–09:00：不运行、不轮询、不要求回执。23:00 这一档最晚到 23:15；此后到次日 08:45 为夜窗。
- 红线事件不受节拍限制：若本会话在夜窗被唤醒且 Issue #9 出现红线 `dispatch-comment`，当轮立即处理。夜间没有另设轮询进程，不能在未唤醒时主动发现红线。

## 2. 三个地址（名字互不可替换）

| 角色 | 地址 | 名字 |
|---|---|---|
| 发布源（权威） | 本仓库 [Issue #9](https://github.com/shugnn/AIStudioOS-Grok/issues/9) 的一条评论，必须含卡片全文 + `card_sha256` + 观察轨 commit | `dispatch-comment` |
| 存档与指纹锚 | 观察轨仓 `_observe/tasks/<task_id>/任务卡.md`，仅校验用，不是取件入口 | `task-card` |
| 回执与产物 | 本仓库 `worker_outbox/<task_id>/`，只放 `ack.json`、产物、封存件，不是入站口 | `worker-outbox` |

两处正文不一致时，以 `dispatch-comment` 为准。只给观察轨仓链接、没有卡片全文的评论，不等于已发卡。不得用存档正文代替评论发 ACK。历史目录映射见 `worker_outbox/PATHS.md`。新任务一律 `worker_outbox/<task_id>/`。

## 3. 轮询命令

实际取件进程是 Grok Bot 例行任务「AIStudioOS dispatch 巡检」（id `aistudioos-task-inbox`）：

- 日程：`CRON_TZ=Asia/Shanghai 0 9,11,13,15,17,19,21,23 * * *`
- 窗口：flexible，提前或延后最多 15 分钟（服务器起点为 `52 8,10,12,14,16,18,20,22`，即 08:52 起每两小时）。
- 不是 GitHub Actions（本仓库 workflow 数为 0；Actions 日程必须在默认分支，当前约定不改 `main`）。
- 不是主机 crontab：乌斑兔用户 crontab 在 2026-11-20 23:43 已删除 `# DS-T7-20261115` 的每 5 分钟与 `@reboot` 两行；现仅剩与取件无关的 `AISTUDIO-SENTINEL`（每小时 `run.sh`、每 15 分钟 `run-watchdog.sh`）。主机 cron 不能唤醒本 bot，也不能完成 ACK。因此没有再安装“扫 Issue #9”的本机 cron，避免造成第二条取件通道的假象。

每轮固定顺序：

1. 读本文件与 `worker_outbox/INBOX_STATE.json`（工人分支 `bot/ds-p2-20261120`，并与本机 `/workspace/worker_outbox/INBOX_STATE.json` 对齐）。
2. 拉取 [Issue #9](https://github.com/shugnn/AIStudioOS-Grok/issues/9) 评论，过滤 `comment.id > last_seen_comment_id`。
3. 识别新的 `dispatch-comment`（须含卡片全文、`card_sha256`、观察轨 commit）及其他须同步的裁定。
4. 发 ACK 或 `INTAKE_FAILURE` 之前，先在 Issue #9 远端去重。
5. 回执写到 Issue #9，产物写到 `worker_outbox/<task_id>/`，且可公开取回。
6. 处理完成后把水位推进到本轮见到的最大 `comment.id`（先回执，再写水位，避免先推进导致漏单；若回执已发出但水位未写入，靠远端去重防止重复 ACK）。

## 4. 水位字段

文件：`worker_outbox/INBOX_STATE.json`（只在工人分支维护，不改 `main`）。

| 字段 | 含义 |
|---|---|
| `schema` | `inbox_state.v1` |
| `repo` | `shugnn/AIStudioOS-Grok` |
| `issue_number` | `9` |
| `last_seen_comment_id` | 已处理的最大 Issue 评论 id（整数） |
| `last_seen_comment_created_at` | 该评论的 GitHub `created_at` |
| `updated_at` | 本水位写入时间（亚洲/上海偏移） |
| `state_branch` | 本文件所在分支 |

同一 `comment.id` 的事后编辑不会再次进入过滤集（已知限制，记入失败原因，不假装能发现）。

## 5. 取件、去重与回执

- 只接受 `intake_mode=auto`。创始人不再转贴；私聊转贴不是任何兜底，不得据此发 ACK。不得把人工轮或创始人发言轮记为 `auto`。
- 同轮次须在本轮启动后 30 分钟内发出 `ACK <task_id>` 或 `INTAKE_FAILURE <task_id> <原因>`。
- 发 ACK 前必须检索 Issue #9 是否已有同 `task_id` 的 `ACK` 或 `INTAKE_FAILURE`：已有则不再发，只补水位与本地 `ack.json`（若缺失）。
- `ACK <task_id>` 必含：`intake_latency_effective_s`、`intake_mode=auto`、实际读到的 `card_sha256`、承诺交付时间、预算口径，以及 `pickup_round_utc`（该轮计划或实际触发时刻）。缺一项视为回执不完整。
- `card_sha256` 必须是本轮从 `dispatch-comment` 正文实际读到的卡片全文（UTF-8 字节）指纹，并与评论声明值一致。不一致，或缺少全文 / `card_sha256` / 观察轨 commit，或全文编码损坏导致无法与声明值核对，视为未收到，发 `INTAKE_FAILURE`，不得发 ACK，也不得改用指纹锚存档正文顶替。
- 交付与 `SEALED <manifest_sha256>` 同样回 Issue #9，并给出工人分支上可公开打开的路径（任何人无需私聊即可取回）。

`intake_latency_effective_s` = ACK 评论 `created_at` 与 `dispatch-comment` 的 `created_at` 之间、落在当日及跨日 09:00–23:00（亚洲/上海）之内的秒数。00:00–09:00 与 23:00–24:00 不计入。抖动耗时若落在 09:00–23:00 内，照常计入。该字段必须如实上报，但不再作为硬上限。

## 6. 主判据与延迟观测

依据 [comment 7054705152](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7054705152)，硬门禁改为 `first_round_ack`：首次 ACK 必须落在发布后的第一个取件轮次内（该档 ±15 分钟），`miss_count=0`。`intake_latency_effective_s` 降为观测值，不设硬上限。

发布对齐义务在观察轨：新卡在取件点前 ≤15 分钟发布（观察轨发布窗 08:45/10:45/…/22:45），夜间发布顺延次日 08:45。

仍保留：`ack_completeness=100%`（含 `card_sha256`、`intake_mode`、`promised_delivery_at`、`budget_basis`，以及本轨增报的 `pickup_round_utc`）。

在上述日程下，相邻窗口之间有 90 分钟空档（例如 09:15 结束，10:45 下一档最早启动）。上界（诚实观测值）：发卡落在窗口刚结束后（例如 09:16），下一轮最早 10:45 启动、最迟约 11:15 回执，有效延迟约 7140 秒（全在 09:00–23:00 内）。夜窗发布的卡片，有效延迟从次日 09:00 起算。本通道不保证任意发布时间都短期回执。

## 7. 夜间策略

- 例行任务在 23:15 之后至次日 08:45 不启动。
- 此期间不轮询 Issue #9，不要求回执；不把夜窗等待计入 `intake_latency_effective_s`。
- 无转贴补漏。次日第一档（08:45–09:15）按水位自动取件。
- 红线见第 1 节：无夜间轮询，仅在被唤醒时立即处理。

## 8. 失败处理

未在自己轮次取到或不能诚实 ACK 时，在 Issue #9 回：

`INTAKE_FAILURE <task_id> <原因>`

并在 24 小时内提交本文件的整改（仍推工人分支，不改 `main`），不得等待转贴。观察轨记 `intake_mode=failed`、任务顺延、不计本轨延迟责任。连续 3 次失败，该轨由观察轨标为「通道不可用」。

编码损坏、声明指纹与评论正文不一致、缺全文或缺观察轨 commit，均走本条，不使用存档正文或私聊转贴补发 ACK。

## 9. 边界与验收

- 不改 `main`、不合并 PR、不付费、不修改其他仓库。
- P3 在本文件与 `worker_outbox/PATHS.md`、`worker_outbox/INBOX_STATE.json` 到位后才发布，不测旧管道。
- 验收（由观察轨测量，不接受自述单独生效；7054705152 修正后）：主判据 `first_round_ack`（首次 ACK 落在发布后第一个取件轮次，`miss_count=0`），`intake_mode=auto`，`ack_completeness=100%`。`intake_latency_effective_s` 为必须如实填报的观测值，不设硬上限。

## 10. 整改记录（2026-11-21 11:00 档）

- 观察轨裁定 [7054705152](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7054705152)：两份 INBOX.md 已核验，通道正式建立，并修正 §六判据（已写入第 6、9 节）。
- [DS-P3-20261121](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7056141600) 于 10:45:25 +08 发布，本轮 10:52:32 +08 取到。评论已含声明 `card_sha256` 与观察轨 commit，但「卡片全文」区间为乱码，计算指纹与声明值 `c739a9142bccae20d9ab807d7f9193a90f4218b72f0d98d9348c0a255d2238b9` 不符。
- 已在首轮回 [INTAKE_FAILURE 7056271954](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7056271954)（10:57:06 +08，`intake_latency_effective_s=701`）。指纹锚 `_observe/tasks/P3-20261121/任务卡.md`（commit `784bc20`）与声明值一致，但未用作取件入口。声明短 SHA `a75c018` 在 AIStudioOS-DS 上未能解析。
- 证据：`worker_outbox/DS-P3-20261121/intake_failure.json`（工人分支）。等待观察轨按 UTF-8 原文重发可核对指纹、可解析观察轨 commit 的 dispatch-comment。
