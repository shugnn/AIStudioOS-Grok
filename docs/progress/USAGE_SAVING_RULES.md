# 自动化省用量约定（2026-11-09）

1. 心跳 + 队列检查 = **同一次 run、同一次** Issue #9 评论  
2. 写出心跳、状态行或任务入口 note 之前，必须先读本仓 Issue #9 评论（`scripts/ds_issue9.py`），同步最新裁定（ACCEPTED / CONDITIONAL / REJECTED）与是否有新的正式任务卡。`task_inbox/` 仍是入口之一，但不能是唯一入口。禁止在已有裁定之后继续写 `L2 pending` 或 `L2 not started`。仍禁止无变更重复 push、长文与交叉评审。本仓脚本不能代替 grok.com / grok-by-xai 停发过期 note，除非那一侧改为调用同一 helper。  
3. 评论一行模板：`heartbeat utc=… next_wake_utc=… status=idle|work queue=empty|has_task`  
4. 调度：09:00–22:00 Asia/Shanghai 约每小时；另 16:00 状态行  
5. 以 grok.com Usage 周池斜率核对是否省到  
