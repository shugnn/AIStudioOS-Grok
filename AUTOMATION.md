# 自动化分档（A/B 类）

仓库：https://github.com/shugnn/AIStudioOS-Grok  
文档日期：2026-11-21（亚洲/上海）  
依据：[Issue #9 comment 7057637233](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7057637233)、[comment 7057776146](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7057776146)。  
本文件在工人分支维护，不改 `main`。取件入口仍是 Issue #9 的 `dispatch-comment`。

## 1. A 类 · 固定心跳

| 项 | 现行配置 |
|---|---|
| 进程 | Grok Bot 例行任务「AIStudioOS dispatch 巡检」（id `aistudioos-task-inbox`） |
| 触发 | `CRON_TZ=Asia/Shanghai 0 9,11,13,15,17,19,21,23 * * *`（每日，含周末） |
| 抖动 | flexible ±15 分钟（计入 `intake_latency_effective_s`）；服务器起点约为 `52 8,10,12,14,16,18,20,22` |
| 夜间 | 00:00–09:00（亚洲/上海）不运行、不轮询、不要求回执。23:00 档最晚到 23:15。 |
| 无新卡 | 静默，不在 Issue #9 发心跳。 |
| 职责 | 证明仍按节拍醒来；按水位读取 Issue #9；在自己的轮次内完成 ACK / `INTAKE_FAILURE` 闭环。 |

取件节拍按观察轨要求保持 09/11/…/23 每 2 小时，**不**改成观察轨那种每小时 :45、24/7。另有「AIStudioOS 日间主动推进」（工作日约 09:00）和「ChatCL 退款晨检」，都不是取件心跳。

主机 crontab 不能唤醒本 bot，也不能完成 ACK。乌斑兔已无「每 5 分钟扫 task_inbox」的条目，也不再另装本机扫 Issue 的 cron。

## 2. B 类 · 一次性任务型观察

**支持。** 用 Grok Bot 一次性例行任务：钉到具体时刻（exact），到点判断，判完删除，不设周期。

五条硬规则：

1. 一次性，不设周期；跑完即删，避免次年同日误触发。
2. 同时挂起不超过 5 条；每条写清：在等什么、判据、判完做什么。
3. 与某次 A 类计划时刻相差 ≤20 分钟则撤 B 类（去重）。观察轨要求的「取件轮 +20 分钟自查」落在 A 类窗口结束之后（例如 15:00 档最晚 15:15，自查在 15:20），作为窗口关闭后的自证保留；若自查时刻会与下一档 A 类窗口重叠，则撤 B、改由那一档 A 类处理。
4. B 类同样更新水位 / `automation_log.jsonl`，不另开取件通道。
5. 事件提前解决（例如 A 类已发出 ACK 或 `INTAKE_FAILURE`）则删除这条 B，不空跑。

默认自证：每张新的有效 `dispatch-comment`，在其首个取件轮计划时刻 +20 分钟设一条自查，判断本轮是否已有 `ACK <task_id>` 或 `INTAKE_FAILURE <task_id>`。已发出则只记日志并删除；未发出则补 `INTAKE_FAILURE`（若尚无）并通知创始人，再在 24 小时内交整改。

## 3. 漏设 / 漏投递如何补救

- 未设 B 类或 B 类未跑：下一档 A 类（最多间隔约 2 小时）按水位补读 Issue #9，不把私聊转贴当补救。
- 本应在首轮取到却未回执：Issue #9 发 `INTAKE_FAILURE <task_id> <原因>`，24 小时内交 `INBOX.md` 或本文件整改。
- 例行任务未能实际唤醒：记 `UNVERIFIED` 或失败原因，不编造成功；连续 3 次由观察轨标「通道不可用」。
- 夜窗（00:00–09:00）不补设取件轮询；红线仅在本会话被唤醒时立即处理。

## 4. 与观察轨的对齐点

- 通道以 Issue #9 的 `dispatch-comment` 为准；`task-card` 只作指纹锚；产物在 `worker_outbox/<task_id>/`。
- 硬门禁是 `first_round_ack`（首次回执落在发布后第一个取件轮次）。`intake_latency_effective_s` 是观测值，须同时报 `pickup_round_utc`。只计 09:00–23:00。
- 每次 `ACK` / `SEALED` 末尾加一行：`下次醒 HH:MM`（亚洲/上海，下一档 A 类计划整点）。
- 实验期 2026-11-21 13:00 至 2026-11-23 10:00（亚洲/上海）。遥测文件：`worker_outbox/automation_log.jsonl`（一行一条本地事实，¥0，不为遥测增加付费调用）。截止 2026-11-22 20:00（亚洲/上海）交本文件与该日志。
- 节拍变更须双方同意，不单方改。不能自证的部分写 `UNVERIFIED`，不猜。

## 5. 边界

不改 `main`、不合并 PR、不付费、不修改其他仓库。
