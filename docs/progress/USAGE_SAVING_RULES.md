# 自动化省用量约定（2026-11-09）

1. 心跳 + 队列检查 = **同一次 run、同一次** Issue #9 评论  
2. 默认禁止：先读 Issue/commits 再评论；禁止无变更重复 push；禁止长文与交叉评审  
3. 评论一行模板：`heartbeat utc=… next_wake_utc=… status=idle|work queue=empty|has_task`  
4. 调度：09:00–22:00 Asia/Shanghai 约每小时；另 16:00 状态行  
5. 以 grok.com Usage 周池斜率核对是否省到  
