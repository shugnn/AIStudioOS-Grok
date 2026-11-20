# worker_outbox 路径映射

仓库：https://github.com/shugnn/AIStudioOS-Grok  
文档日期：2026-11-21（亚洲/上海）  
依据：[Issue #9 comment 7044312076](https://github.com/shugnn/AIStudioOS-Grok/issues/9#issuecomment-7044312076)。  
历史目录保留不迁移；本表只做对照。新任务一律 `worker_outbox/<task_id>/`。

| task_id | 角色 | 路径 | 说明 |
|---|---|---|---|
| DS-T1-20261108 | 历史（不迁移） | `task_inbox/DS-T1-20261108/` | 默认分支 `main` 上的历史目录（曾用 `TASK.md`）。 |
| DS-T7-20261115 | 历史（不迁移） | `task_inbox/DS-T7-20261115/` | 封存件在既有工人分支/目录，路径不迁。 |
| DS-P1-20261120 | 历史（不迁移） | 分支 `bot/ds-p1-20261120` 的 `task_inbox/DS-P1-20261120/` | 协议点名之外的已封存旧路径，同样不迁。 |
| DS-P2-20261120 | 协议生效前已发布并 ACK | 分支 `bot/ds-p2-20261120` 的 `task_inbox/DS-P2-20261120/` | 卡面当时要求该旧目录。已发出的 ACK 不迁；剩余产物仍按该卡路径提交，除非观察轨另示改到 `worker_outbox/`。 |
| 本协议生效后的新任务（含 P3） | `worker-outbox` | `worker_outbox/<task_id>/` | 只放 `ack.json`、产物、封存件；不是入站口。水位文件见同目录上一级的 `INBOX_STATE.json`。 |

取件入口始终是 Issue #9 的 `dispatch-comment`，不是上表任一目录。
