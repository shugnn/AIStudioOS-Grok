# 工人取件通道（INBOX）

仓库：https://github.com/shugnn/AIStudioOS-Grok  
文档日期：2026-11-20（亚洲/上海）  
性质：如实记录**当前**取件通道，并写明目标协议。不把未上线的机制写成已在跑。

## 1. 唯一收件箱

目标路径规范：

- 目录：`task_inbox/<task_id>/`
- 任务卡文件名：`任务卡.md`（历史 T1 曾用 `TASK.md`，新卡统一用 `任务卡.md`）
- 必含字段：`task_id`、目标、交付物、截止
- 取件回执：同目录 `ack.json`
- 指标记录：同目录 `intake.json`（含 `intake_latency_s`）

**当前事实（2026-11-20 核实）：**

- 本仓库默认分支 `main`（`a081c2e985ecae06b1e30ce9fd93be4b301ca5e0`）的 `task_inbox/` **只有** `DS-T1-20261108/`（`TASK.md`、`dispatch.json`、`worker_jobs.py`），没有 P1/P2 的任务卡目录。
- 观察轨官方卡的实际发布入口是 [Issue #9](https://github.com/shugnn/AIStudioOS-Grok/issues/9) 评论；全文在观察轨仓 `AIStudioOS-DS` 的 `_observe/tasks/<短号>/任务卡.md`。
- 本轮 P2 卡文件路径（不在本仓库）：https://github.com/shugnn/AIStudioOS-DS/blob/main/_observe/tasks/P2-20261120/任务卡.md  
  发布评论：[Issue #9 comment 7039777786](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7039777786)  
  ref=`main`，size=5006，git blob SHA `24f03ecd0b8a6f25b5bbfe4e06b09c0aee563721`。
- 交付物另放在工人分支 `bot/<task_id>/task_inbox/<task_id>/`，不得改 `main`、不得为此合并 PR。

## 2. 取件协议

### 2.1 当前正在运行的机制

- **不是** GitHub Actions：本仓库 `list_workflows` 返回 `total_count=0`，默认分支也没有 `.github/workflows/`。
- **不是** 仓库内或主机上的 crontab 守护进程在监视 `task_inbox/`。
- **是** Grok Bot 例行任务「AIStudioOS task_inbox 巡检」（id `aistudioos-task-inbox`）：
  - 日程：`CRON_TZ=Asia/Shanghai 0 9,11,13,15,17,19 * * 1-5`
  - 窗口：可提前或延后最多 15 分钟（服务器实际起点为 `45 8,10,12,14,16,18 * * 1-5`）
  - 工作日 09:00–19:00（亚洲/上海）每 2 小时一轮；周末无槽。
  - 每轮读取 [Issue #9](https://github.com/shugnn/AIStudioOS-Grok/issues/9) 最新评论，并检查 `task_inbox/`；若有新官方卡或新裁定，须在当轮回 Issue ACK，并在本聊天通知创始人。
- 另有「AIStudioOS 日间主动推进」，工作日约 09:00 一次，不是 2 小时收件巡检。

### 2.2 取到后第一步（本协议，即日起执行）

1. 写下 `task_inbox/<task_id>/ack.json`（本分支，不改 `main`）。
2. 在 Issue #9 回一行：`ACK <task_id>`，并写明 `task_id`、承诺交付时间、预算口径、`intake_latency_s`、任务卡 SHA256（或无法逐字节核验时的诚实说明）、以及触发类型。
3. 任何卡取到后 **30 分钟内**完成上述 Issue ACK。
4. 若由创始人私聊转贴才发现，必须注明「人工转贴触发」，不得记为自动。

## 3. 失效兜底（必须写明）

- 工作日 19:00 窗口结束之后，到下一个工作日 08:45 之前，以及整个周末：**没有已上线的自动取件进程**。
- 这段时间若要在 30 分钟内 ACK，**当前唯一可靠入口是创始人私聊转贴或一次被唤醒的会话**。不是“也许还有别的守护进程”。
- 发现方式：目前没有独立的看门狗。漏检要等下一档工作日巡检、创始人转贴、或人工查看 Issue #9 才会被发现。
- 恢复时间：下一档巡检最多间隔约 2 小时（仅工作日 08:45–19:15）；若卡发在周五 19:15 之后，自动恢复要等到下周一 08:45，可能超过 60 小时。
- 本仓库没有 GitHub Actions 可在巡检挂掉时顶上。若要加密巡检或加 Actions，必须先在 Issue #9 报方案与影响面，经创始人批准后再上，不得自行启用。

## 4. 回执义务

Issue ACK 必须在取到后 30 分钟内发出，内容至少含：

- `task_id`
- 承诺交付时间
- 预算口径（本指令与 P2 均为 ¥0 / 0 次模型调用）
- `intake_latency_s`
- 任务卡文件 SHA256（能逐字节核验时）；否则写明障碍，不虚报
- 触发类型：`巡检自动` 或 `人工转贴触发`

## 5. 监测指标

`intake_latency_s` = ACK 时刻 − 发布时刻（秒）。

- ACK 时刻以 Issue 评论的 GitHub `created_at` 为准。
- 发布时刻：同时记录（a）任务卡声明时间、（b）Issue 发布评论 `created_at`，两条都写，避免口径混用。
- 硬指标（由观察轨测量，不接受自述单独生效）：`intake_latency_s ≤ 1800`（目标 ≤ 600）；发布后 60 分钟内无 ACK 记一次漏单；自动 ACK 不得把人工转贴写成自动。

已发生记录：

| task_id | 发布（+08） | ACK（+08） | intake_latency_s | 触发 | 漏单（60min） |
|---|---|---|---:|---|---|
| DS-P1-20261120 | 2026-11-19 23:57:48（[7014411433](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7014411433)） | 2026-11-20 08:56:23（[7026936065](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7026936065)） | 32315 | 巡检自动（次日 09:00 窗口） | 是 |
| DS-P2-20261120 | 卡面 2026-11-20 20:45:00；Issue 20:40:21（[7039777786](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7039777786)） | 2026-11-20 20:57:23（[7040111914](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7040111914)） | 743（相对卡面）/ 1022（相对 Issue） | 人工转贴触发 | 否 |

P1 空窗证据：Issue #9 在 7014411433 与 7026936065 之间无任何评论；本仓库 Actions 为 0；巡检 cron 在 19:00 之后、次日 08:45 之前无槽。这是日程空窗，不是“进程在重试但失败”的日志。

## 6. 待批方案（未上线）

为达到 `intake_latency_s ≤ 1800`（目标 ≤ 600）且漏单数为 0，需要加密取件。**尚未启用。** 建议在 Issue #9 讨论后由创始人批准再改：

- 将「task_inbox 巡检」改为每日（含周末）08:00–22:00 每 15 或 30 分钟一轮，仍只读 Issue #9 与 `task_inbox/`，仍 ¥0，不改 `main`、不合并 PR、不触碰其他仓库。
- 影响面：例行唤醒次数增加，用量上升；仍依赖 Grok Bot 例行任务能够实际跑起来，不是主机 cron，也不是 Actions。
- 若要把官方卡文件同步进本仓库 `task_inbox/<task_id>/任务卡.md` 以便就地计算 SHA256，也须单独批准（可只推到工人分支，不改 `main`）。

