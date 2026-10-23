# Cross-Team Communication Protocol

**Date**: 2026-10-23  
**Tracks**: AIStudioOS-Grok ↔ AIStudioOS-ChatGPT  
**Audience**: Founder (shugnn), Grok team, ChatGPT team

## 1. Goal

建立双方可观察、可追溯、可回复的沟通机制，使：

- 创始人能随时掌握两边进度与阻塞
- 两个 AI 团队能互相阅读对方的关键决策与实验结果
- 重要审阅、批准、重大调整都沉淀在 GitHub 上，而不是只存在于聊天窗口

## 2. Primary Channel: GitHub

| 类型 | 使用方式 | 标签 |
|------|----------|------|
| 设计审阅 / 批准请求 | Issue | `review-request`, `approval-needed` |
| 阻塞事项 | Issue | `blocker` |
| 每日/阶段进度报告 | Issue 或 `docs/progress/` 文件 | `progress-report` |
| 跨团队讨论 | Issue 评论 或 Discussion（若开启） | `cross-team` |
| 代码与实验 | Commit + PR | — |
| 重要节点 / 里程碑 | GitHub Milestone + Release（可选） | — |

**原则**：聊天中的重要结论，必须同步落到 GitHub Issue 或文档，否则视为未正式沟通。

## 3. Dual-Track Daily / Periodic Progress Report

报告应包含以下固定章节：

1. **仓库活动**  
   - AIStudioOS-Grok：新 commits / PRs / Issues  
   - AIStudioOS-ChatGPT：新 commits / PRs / Issues（若可访问）

2. **本阶段完成的功能与测试结果**

3. **当前阻塞事项**（含负责人与期望解除方式）

4. **实际开发进度 vs 计划 / 验收结果**

5. **需要创始人审批的事项**（明确列出选项与建议）

6. **对另一轨道的观察与建议**（可选，保持建设性）

报告文件建议路径：

- `docs/progress/YYYY-MM-DD-dual-track-report.md`
- 同时开一个带 `progress-report` 标签的 Issue，方便对方评论

## 4. Review & Approval Flow

1. 需要审阅的一方在本仓库（或对方仓库）开 Issue，标题以 `[Review Request]` 或 `[Approval Needed]` 开头。
2. 在 Issue body 中写清：背景、设计摘要、具体问题、相关 commit。
3. 创始人或其指定代表（当前为 ChatGPT 团队可代为回复）在 Issue 下评论。
4. 提出方根据评论修改，关闭 Issue 或标记为 resolved。

**当前开放的审阅**：  
→ https://github.com/shugnn/AIStudioOS-Grok/issues/1  
（Control Plane Phase-1 Design）

## 5. Observability Expectations

- Grok 轨道：尽量把工作要点、阻塞、建议、批准请求提交到 **本仓库**。
- ChatGPT 轨道：建议同样在 `shugnn/AIStudioOS-ChatGPT` 建立对应 Issue / 文档；若该仓库尚未创建或不可见，Grok 轨道会在进度报告中注明“对方仓库暂不可访问”。
- 双方进度报告互相引用对方 Issue / commit，形成可追溯链条。

## 6. What Goes to GitHub (Checklist)

以下事项**必须**落到 GitHub（Issue 或 docs）：

- [ ] 重要设计决策与状态机变更
- [ ] 实验协议锁定与修改
- [ ] 阻塞超过 24h 的问题
- [ ] 需要创始人批准的预算 / 权限 / 范围变更
- [ ] 阶段验收结果与指标数据
- [ ] 对另一轨道有影响的架构调整建议

聊天可用于快速对齐，但结论要回写。

## 7. First Actions Taken by Grok Track (2026-10-23)

1. 创建本协议文档。
2. 创建 Issue #1：Control Plane 设计审阅请求（供创始人 / ChatGPT 回复）。
3. 建立标签体系：`review-request`, `approval-needed`, `blocker`, `progress-report`, `cross-team`, `control-plane`, `phase-1`。
4. 发布第一份双轨进度报告（见 `docs/progress/`）。

---

本协议对 AIStudioOS-Grok 轨道立即生效。ChatGPT 轨道可参考或提出修订。
