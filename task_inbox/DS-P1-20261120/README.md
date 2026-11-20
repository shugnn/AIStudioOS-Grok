# DS-P1-20261120 记账管线

确定性管线：读取本轨已封存的 T7 原始证据包，计算 F1 / F2 / F3 / F6 / F9 / C1，并为每个数字给出源文件+行号溯源。不联网、不调用模型、仅标准库。

## 怎么跑

不要改 T7 原件。把三个封存文件的路径传给管线：

```bash
python3 pipeline.py \
  --summary /path/to/soak_summary.json \
  --timeline /path/to/soak_timeline.jsonl \
  --incidents /path/to/incidents.jsonl \
  --out . \
  --readme README.md \
  --generated-utc 2026-11-20T01:00:00Z
```

成功时在 `--out` 写出 `scorecard.json`、`provenance.json`、`manifest.json`。失败（含坏数据）只在 stderr 打印 `error: <文件>:<行号>: ...`，退出码 2，且**不写出** `scorecard.json`。

`--generated-utc` 只写入 `manifest.json`，不进入记分卡或溯源。省略时用当前 UTC。

## 输入（本轨 T7 原件）

使用已封存原件，SHA256 必须与 T7 manifest 一致：

| 文件 | SHA256 |
|---|---|
| soak_summary.json | `4c365fbad55e747e65ebf425a64f5cd18d24ccc1895d4f514eeab3aaaf8361d1` |
| soak_timeline.jsonl | `db949b1cc884fe782eee10407ac87fcf12501c7767b4341552b6eb8040813321` |
| incidents.jsonl | `72a35319fe713b97c81b000e7dfd8c345f545de754a146820b0c1349c414f6a1` |

公开取回：分支 `bot/ds-t7-20261115`，commit `8a41599c1ce140ba8135a8ac304ea1a50d461654`，目录 `task_inbox/DS-T7-20261115/sealed/`。T0 code_sha `fb6a0eab24293ce79976e6f81732795efe4b2663`。

## 怎么复算

1. **F1 墙钟达成率** = `wall_elapsed_s / planned_s`。`wall_elapsed_s` 由 `soak_summary.json` 的 `t_end_utc - t0_utc` 按 UTC 墙钟重算，并与声明的 `wall_elapsed_s` 交叉核对。`clock_basis` 取包内声明（本包为 `utc_wall`）。
2. **F2 有效轮次率** = `VERIFIED 轮次数 / 应执行轮次`。节拍 `cadence_s` 为相邻 `ts_utc` 间隔的中位数；应执行轮次在 `planned_s` 能被节拍整除时为 `planned_s / cadence_s`。
3. **F3 未解释缺槽数**：相邻轮次间隔大于 `max(600, cadence_s+600)`，且开闭区间 `(prev_ts, next_ts]` 内没有任何 incident 的 `detected_utc` / `detected_at_utc`，计 1 段。
4. **F6 哈希互异**：①同一 `cycle` 出现两次及以上 VERIFIED 的个数；②同一 `sha_full` 被多于一个 cycle 复用的个数。
5. **F9 计划-实际可解释率**：分母为有 `plan_wake` 的轮次。某轮可归因，当且仅当 `ts_utc - plan_wake == 0`，或至少一条 incident 的检测时间落在闭区间 `[plan_wake, ts_utc]`（起止顺序不敏感）。实际唤醒时刻取 `ts_utc`（包内无 `actual_wake` 字段）。
6. **C1 成本声明一致性**：仅在 `total_cost_cny` 数值为 0 时判定：同时给出 `model_calls=0` 则为 true，否则 false。

## 不可得项

- **单调钟**：T7 封存包只有 UTC 墙钟时间戳（`clock_basis=utc_wall`），没有单调钟读数。`metrics.F1.monotonic_elapsed_s` 填 `null`，不编造。这与观察轨已记录的「墙钟为 UTC 口径非单调钟」一致。

## 幂等

对同一输入连续跑两次，`scorecard.json` 与 `provenance.json` 字节相同。`manifest.json` 的 `generated_utc` 若未固定，会随调用时刻变化；`code_sha` 为 `pipeline.py` 的 SHA256。

## 坏数据（A-5）

复制输入后注入一行坏记录再跑。管线必须报错并指出行号，且不得在本次失败运行中写出 `scorecard.json`。
