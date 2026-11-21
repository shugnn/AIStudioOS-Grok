# 自动化分档（A/B 类）

仓库：https://github.com/shugnn/AIStudioOS-Grok  
文档日期：2026-11-21（亚洲/上海）  
依据：[Issue #9 comment 7057637233](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7057637233)、[comment 7057776146](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7057776146)、创始人强制指令 2026-11-21 14:40（亚洲/上海）。  
本文件在工人分支 `bot/ds-p2-20261120` 维护，不改 `main`。取件入口仍是 Issue #9 的 `dispatch-comment`。

四件实物截止：**2026-11-22 10:00（亚洲/上海）**。缺一即视为未执行。路径均在本分支：

1. `AUTOMATION.md`（本文件）
2. `worker_outbox/automation_log.jsonl`
3. `worker_outbox/B_CLASS_PROOF.jsonl`（至少一条真实触发样本）
4. Issue #9 一行回执：`收到并执行：A=<cron>｜B=<机制>｜下次醒 HH:MM`

实验期日志继续记到 2026-11-23 10:00。不为遥测增加付费调用。

## 1. A 类 · 固定心跳

| 项 | 现行配置 |
|---|---|
| 谁触发 | Grok Bot 例行任务「AIStudioOS dispatch 巡检」（id `aistudioos-task-inbox`） |
| 触发时刻 | 北京时间每天 09/11/13/15/17/19/21/23（含周末） |
| cron | `CRON_TZ=Asia/Shanghai 0 9,11,13,15,17,19,21,23 * * *` |
| 抖动 | flexible ±15 分钟（计入 `intake_latency_effective_s`）；服务器起点约为 `52 8,10,12,14,16,18,20,22` |
| 夜间策略 | 00:00–09:00（亚洲/上海）不运行、不轮询、不要求回执。23:00 档最晚到 23:15。 |
| 每轮第一件事 | 读 Issue #9，按 `comment.id > last_seen_comment_id` 过滤。水位在 `worker_outbox/INBOX_STATE.json`。 |
| 有新 dispatch 卡 | 本轮启动后 30 分钟内回 `ACK <task_id>`，字段必须含：`card_sha256` / `intake_mode` / `intake_latency_effective_s` / `promised_delivery_at` / `budget_basis`；并报 `pickup_round_utc`。末尾加 `下次醒 HH:MM`。 |
| 无新卡 | 不发言，不在 Issue #9 发心跳。 |

取件节拍保持 09/11/…/23 每 2 小时，**不**改成观察轨那种每小时 :45、24/7。另有「AIStudioOS 日间主动推进」（工作日约 09:00）和「ChatCL 退款晨检」，都不是取件心跳。

主机 crontab 不能唤醒本 bot，也不能完成 ACK。乌斑兔已无「每 5 分钟扫 task_inbox」的条目，也不再另装本机扫 Issue 的 cron 作为第二条取件通道。

## 2. B 类 · 一次性任务型观察（强制，无豁免）

B 类必须真实存在并运行：到点即触发 → 触发即执行 → 执行即自证 → 用后即清。不得以「平台不支持」为豁免，也不得标 `UNVERIFIED` 后停住。

### 2.1 主机制（平台一次性例行任务）

用 Grok Bot 一次性例行任务：钉到具体时刻（`timing=exact`），到点判断，判完删除，不设周期。

五条硬规则：

1. 一次性，不设周期；跑完即删，避免次年同日误触发。
2. 同时挂起不超过 5 条；每条写清：在等什么、判据、判完做什么。
3. 与某次 A 类计划时刻相差 ≤20 分钟则撤 B 类（去重）。观察轨要求的「取件轮 +20 分钟自查」落在 A 类窗口结束之后（例如 15:00 档最晚 15:15，自查在 15:20），作为窗口关闭后的自证保留；若自查时刻会与下一档 A 类窗口重叠，则撤 B、改由那一档 A 类处理。
4. B 类同样更新水位 / `automation_log.jsonl` / `B_CLASS_PROOF.jsonl`，不另开取件通道。
5. 事件提前解决（例如 A 类已发出 ACK 或 `INTAKE_FAILURE`）则到点仍要触发并自证，已有回执则只写证明、不空发 Issue，然后删除这条 B。

默认自证：每张新的有效 `dispatch-comment`，在 ACK 之外，于其首个取件轮计划时刻 +20 分钟设一条自查，判断本轮是否已有 `ACK <task_id>` 或 `INTAKE_FAILURE <task_id>`。已发出则只记日志与证明并删除；未发出则补 `INTAKE_FAILURE`（若尚无）并通知创始人，再在 24 小时内交整改。

### 2.2 自建兜底（平台创建失败或到点未唤醒时强制启用）

若一次性例行任务无法创建、被拒、或到点未触发，必须立即启用自建方案，不得停在声明：

- 脚本：`worker_outbox/b_class_fire.sh`
- 调度：本计算机上的一次性 `at` 作业（或等价的 `systemd-run --on-calendar` / 后台到点脚本），在 `scheduled_for` 时刻执行该脚本。
- 脚本职责：读取 Issue #9 是否已有本卡 ACK / `INTAKE_FAILURE`；向 `worker_outbox/B_CLASS_PROOF.jsonl` 追加一行（含真实 `fired_utc`）；若本会话可写 GitHub，则把该行推到 `bot/ds-p2-20261120`。脚本不能唤醒本 bot；若回执仍缺，由下一档 A 类补 `INTAKE_FAILURE` 并通知创始人。
- 与主机制并存时须幂等：同一 `task_id` + `scheduled_for_utc` 已有 `fired_utc` 则不再重复动作。

本机 `at` 不能代替 Issue 回执，只作到点自证与补发现。主机 cron 仍不作为第二条取件通道。

### 2.3 证明文件

`worker_outbox/B_CLASS_PROOF.jsonl` 一行一条，字段：`task_id` · `scheduled_for_utc` · `fired_utc` · `one_shot`（true）· `cleanup`（auto|manual）· `action_taken` · `evidence_url`。预约时先写 `fired_utc=null`；真实触发后必须回填 `fired_utc` 与 `evidence_url`。验收只认真实触发样本，不认「已配置」。

首个样本：DS-P3-20261121，计划 2026-11-21 15:20（亚洲/上海），例行任务 id `p3-v2-20min`。

## 3. 漏投递如何发现与补救

- 未设 B 类或 B 类未跑：下一档 A 类（最多间隔约 2 小时）按水位补读 Issue #9，不把私聊转贴当补救；同时启用 §2.2 自建兜底。
- 本应在首轮取到却未回执：Issue #9 发 `INTAKE_FAILURE <task_id> <原因>`，24 小时内交 `INBOX.md` 或本文件整改。不得沉默。
- 例行任务未能实际唤醒：记失败原因并启用自建兜底，不编造成功；连续 3 次由观察轨标「通道不可用」。
- 夜窗（00:00–09:00）不补设取件轮询；红线仅在本会话被唤醒时立即处理。

## 4. 与观察轨的对齐点

- 通道以 Issue #9 的 `dispatch-comment` 为准；`task-card` 只作指纹锚；产物在 `worker_outbox/<task_id>/`。
- 硬门禁是 `first_round_ack`（首次回执落在发布后第一个取件轮次）。`intake_latency_effective_s` 是观测值，须同时报 `pickup_round_utc`。只计 09:00–23:00。
- 每次 `ACK` / `SEALED` 末尾加一行：`下次醒 HH:MM`（亚洲/上海，下一档 A 类计划整点）。
- 实验期 2026-11-21 13:00 至 2026-11-23 10:00（亚洲/上海）。遥测文件：`worker_outbox/automation_log.jsonl`（一行一条本地事实：`ts_utc`、`kind` 或 `round_type`（A/B）、是否扫到新 dispatch、是否发 ACK、`intake_latency_effective_s`、是否漏轮、备注）。¥0，不为遥测增加付费调用。
- 四件实物截止 2026-11-22 10:00（亚洲/上海）；P3 / P2 任务卡本身仍截止 2026-11-22 23:59。
- 节拍变更须双方同意，不单方改。

## 5. 边界

不改 `main`、不合并 PR、不付费、不修改其他仓库。
