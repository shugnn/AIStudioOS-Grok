【正式任务卡 T5-20261112（L3·语义修订·必须调用模型）】TASK ID：`DS-T5-20261112`
> 创始人 2026-11-12 批准。**本题强制模型参与**（条款写死，纯规则实现 = UNVERIFIED）。

## 一、目标
客户用**自然语言**提了四条问题（不给你规则编号）。你要：
1. **调用模型**读懂这段抱怨，判断每条对应报表哪一处错误
2. 修订报表
3. 由产品 Verifier 校验通过
**不得**把抱怨人工翻译成规则再由脚本执行——那不算（见 A-2）。

## 二、输入（复用 T4 数据，SHA 须一致）
`appts.csv`：与 T4 同一文件，**12350 字节 / 301 行 / SHA256 `a82ef503933d3c5edc60e80f5b7f03faf0b3f736a04591de4f9a2338f7a61c28`**

## 三、待修候选（`candidate_v3`）
```json
{
  "total_revenue": 186035.32,
  "by_dept": {
    "med": {
      "count": 78,
      "revenue": 33498.79
    },
    "surg": {
      "count": 67,
      "revenue": 28287.69
    },
    "ped": {
      "count": 80,
      "revenue": 45038.37
    }
  },
  "by_month": {
    "2026-01": 15971.41,
    "2026-02": 13331.09,
    "2026-03": 14048.1,
    "2026-04": 19432.15,
    "2026-05": 16306.24,
    "2026-06": 16227.77,
    "2026-07": 12490.11,
    "2026-08": 18501.38,
    "2026-09": 16277.85
  }
}
```

## 四、客户抱怨原文（唯一线索，无规则编号）
> 财务那边看了这版报表，提了几个问题：
> 1）总营收比实际高不少，取消的和爽约的好像都算进去了；
> 2）科室表里好像少了一个科室，儿科/皮肤科那边对不上；
> 3）各科室"例数"也不对，取消的似乎被数进了就诊例数；
> 4）金额有些是 33498.79，也有 18093.9 这种一位小数的，要求统一两位小数；
> 麻烦改一版，别再出这种问题。月度那块他们没提意见，别乱动。

## 五、交付物
1. `interpretation.json`：逐条 `{"complaint":1,"understood_as":"...","target_path":"total_revenue","fix":"..."}`（4 条）
2. `candidate_v4.json`：修订版
3. `model_usage.json`：**必须≥1 次真实模型调用**，字段：
   `{"step":"interpret_complaint","model":"<模型名>","calls":N,"prompt_tokens":N,"completion_tokens":N,"estimated_cny":"x.xx"}`
   （允许外加其它步骤；`step` 必须含 `interpret_complaint`）
4. `verdict.json`：`{"verdict":"ACCEPTED","checks":[...]}`
5. `manifest.json`

## 六、验收（我方独立复算）
- A-1 数据 SHA 一致
- A-2 **`model_usage.calls ≥ 1` 且 `interpret_complaint` 步骤有真实 token 记录**；
     若 `calls=0` 或全为规则实现 → 判 **UNVERIFIED**（不算失败，但本题能力未验证）
- A-3 `candidate_v4` 与我方复算**完全一致**（含 **勿动月度** —— 月度本身是对的，改了即错）
- A-4 `interpretation.json` 4 条且与抱怨语义对应
- A-5 `verdict.json` = ACCEPTED
- A-6 `model_usage.estimated_cny ≤ 5.00`（D-023 单次上限）；无费用记录 → UNVERIFIED

## 七、边界
零付费以外仅限 D-023 额度 · 仅允许模型 API 出网 · 不改对方仓
**截止：确认后 48 小时**

—— 观察轨（DS）代发
