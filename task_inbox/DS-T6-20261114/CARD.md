【正式任务卡 T6-20261114（L4·有界自我迭代）】TASK ID：`DS-T6-20261114`
> 创始人 2026-11-14 批准。**本题考察：自己定策略、迭代、评估收益、以及在边界内停下来。**

## 一、目标
把一份**只有 1/5 合格项**的报表，通过**逐轮迭代**修到 **5/5**。
**每一轮只处理一项不合格**；由**模型**决定"这一轮修哪一项、为什么"。

## 二、输入（复用 T4/T5 数据）
`appts.csv`：**12350 字节 / 301 行 / SHA256 `a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28`**

## 三、v0 候选（`candidate_v0`）
```json
{
  "total_revenue": 186035.32,
  "by_dept": {
    "med": {
      "count": 78,
      "revenue": 42211.74
    },
    "surg": {
      "count": 67,
      "revenue": 40186.6
    },
    "ped": {
      "count": 80,
      "revenue": 54911.06
    }
  },
  "by_month": {
    "2026-01": "15971.41",
    "2026-02": "13331.09",
    "2026-03": "14048.10",
    "2026-04": "19432.15",
    "2026-05": "16306.24",
    "2026-06": "16227.77",
    "2026-07": "12490.11",
    "2026-08": "18501.38",
    "2026-09": "16277.85"
  }
}
```

## 四、评分规则（5 项，各 1 分）
| 项 | 通过条件 |
|---|---|
| R1 | 所有金额为**两位小数字符串** |
| R2 | `by_dept` 含 **4 个科室** med/surg/ped/derm |
| R3 | `by_month` 键**升序**且覆盖数据中出现的全部月份 |
| R4 | **仅 `status=completed`** 计入 `count` 与 `revenue`（含 `total_revenue`） |
| R5 | 顶层含 `generated_from` 字段，值为输入 SHA256 |

v0 当前 **1/5**（仅 R3 通过）。

## 五、迭代规则（硬性）
- 每轮：**模型**读当前分数与未通过项 → 决定本轮只修哪一项 → 修订 → 重评分
- 记录每轮：`round` / `rule_targeted` / `model_reasoning`（≤120 字）/ `score_before` / `score_after` / `cost_cny`
- **停止条件（任一满足即停，不得继续）**：
  ① 分数达到 5/5；② 轮数达到 **8**；③ **连续 2 轮无提升**
- 停止后如实写 `stop_reason`

## 六、交付物
1. `iterations.jsonl`（每轮一行，字段见上）
2. `final_candidate.json`
3. `stop_report.json`：`{"stop_reason":"SCORE_5|ROUNDS_8|NO_IMPROVEMENT","rounds":N,"final_score":"x/5","goal_status":"ACHIEVED|PARTIAL","total_cost_cny":"x.xx","total_tokens":N}`
4. `verifier_final.json`：5 项逐条通过/不通过 + 理由

## 七、验收（我方独立复算）
- A-1 输入 SHA 一致
- A-2 `final_candidate` 5 项**全部通过**（我方复算，非自测）
- A-3 `iterations.jsonl` **≥2 轮**，且**每轮只改一项**（改多项视为无效轮，扣分）
- A-4 **每轮都有模型调用留痕**（`model_reasoning` + token/费用）；无模型参与 → UNVERIFIED
- A-5 `stop_reason` 与轮数/分数自洽；**达到 5/5 后仍在迭代 = 违反停止条件**
- A-6 总费用 ≤ **¥5**（D-023）；`total_cost_cny` 与逐轮相加一致

## 八、边界
零付费以外仅限 D-023 · 仅模型 API 出网 · 不改对方仓 · **允许占用机器数小时**
**截止：确认后 72 小时**（本题允许长跑）

—— 观察轨（DS）代发
