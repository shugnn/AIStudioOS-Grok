# DS-T7-20261115 监督声明

- 任务：无人干预连续运行 72 小时，全程留证。72h ≠ 生产 7×24。
- 主机：Laisg-Ubuntu。入口：`scripts/worker_run_task.py --task-id DS-T7-20261115`。
- 心跳间隔：5 分钟（≤10 分钟）。
- 双进程互看：`runner` 做轮次工作；`guardian` 每 2 秒检查 runner。任一方被杀，另一方或 cron ensure 在 ≤10 秒内写入 `incidents.jsonl` 并拉起。
- 第三路：用户 crontab 每 5 分钟执行 `t7_soak.py ensure`，`@reboot` 延迟 20 秒后再 ensure。
- 自行恢复：崩溃后由 guardian 或 cron 自动继续；人工介入必须记入 incidents 并视为 CONDITIONAL。
- 幂等：每轮 `idempotency_key=plan_wake`；相同键不重复追加产物。
- 时钟：timeline 记录 plan_wake 与 actual_wake；偏差 >2× 轮间隔（30 分钟）必须写 explanation。
- 失败三分归因：business / host / supervision，不以 unknown 收尾。
- 费用上限：¥1.00；默认确定性巡检，cost_cny=0。
