# Founder decisions

## Closed

| ID | 中文 | Result |
|----|------|--------|
| D1 | Windows 约24小时墙钟浸泡 | **PASS** |
| Ubuntu-24H | Ubuntu 约24小时墙钟浸泡 | **PASS** |
| R3 | 监督掉线注入（30秒黄 / 6分钟红） | **PASS** |
| L2-4 | Windows 计划任务一日值守 | **INCOMPLETE** |
| L2-2 | 约72小时加长浸泡 | **取消**（与24h同类重叠，创始人 2026-11-07 否决） |

## Active next（非重叠）

| 中文 | 脚本 | 目的 |
|------|------|------|
| 中途强杀再拉起 | `scripts/run_recovery_drill.py` | 恢复能力，不是比谁跑得久 |
| 急停文件演练 | `scripts/run_emergency_stop_drill.py` | 急停开/关是否按设计生效 |

## Open

| 中文 | 默认 |
|------|------|
| 跨轨小实验 J-Exp-01 | 仅设计 |
| 打版本标签 | 不自动打 |
| 开机任务 / 改电源 | 默认拒绝 |
