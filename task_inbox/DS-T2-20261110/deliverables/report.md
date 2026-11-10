# DS-T2-20261110 月度经营报告

## 概况

- task_id: `DS-T2-20261110`
- 订单行数（不含表头）: 6000
- total_amount: 5983804.03
- 金额口径: `total_amount` 与各分组 `amount` 均为 amount 列直接加总，两位小数字符串；不按 paid/refunded/cancelled 轧差。分组计数见 `orders`。
- orders.csv sha256: `633aded091b1da111f4c3c9c378c975d3bdddf17e85a0fd3b001c7e4ddbf7ffe`
- bytes: 237705（期望 237705）
- lines: 6001（期望 6001，含表头，UTF-8 / LF / 无 BOM）
- fingerprint_match: true
- 生成: seed=20261108，观察轨 Issue #9 冻结脚本，离线确定性。
- 本报告由产品 Worker 路径写出。生产 7×24 **未验收**；观察轨尚未独立复算。

## 月度

| 月份 | 订单数 | 金额 |
|------|--------|------|
| 2026-01 | 667 | 668850.24 |
| 2026-02 | 631 | 609611.59 |
| 2026-03 | 716 | 736710.12 |
| 2026-04 | 633 | 629907.82 |
| 2026-05 | 688 | 670223.99 |
| 2026-06 | 639 | 642742.70 |
| 2026-07 | 677 | 675958.80 |
| 2026-08 | 683 | 679097.14 |
| 2026-09 | 666 | 670701.63 |

## 分布

### 状态

| status | 订单数 | 金额 |
|--------|--------|------|
| paid | 4175 | 4166663.94 |
| pending | 1236 | 1241939.77 |
| refunded | 371 | 358073.32 |
| cancelled | 218 | 217127.00 |

### 渠道

| channel | 订单数 | 金额 |
|---------|--------|------|
| web | 3020 | 2983433.46 |
| app | 2098 | 2100063.74 |
| store | 882 | 900306.83 |

## Top10

金额降序，同额按 customer_id 升序。

| 排名 | customer_id | 订单数 | 金额 |
|------|-------------|--------|------|
| 1 | C0641 | 14 | 17000.42 |
| 2 | C0362 | 18 | 16755.97 |
| 3 | C0281 | 18 | 16367.99 |
| 4 | C0483 | 11 | 16143.76 |
| 5 | C0375 | 12 | 16020.91 |
| 6 | C0734 | 15 | 16020.60 |
| 7 | C0730 | 13 | 15965.44 |
| 8 | C0019 | 15 | 15765.55 |
| 9 | C0732 | 15 | 15299.41 |
| 10 | C0316 | 14 | 14957.55 |

## 异常

规则: A1 amount<10.00；A2 status=cancelled 且 amount>1000.00；A3 order_id 重复；A4 日期越界（不在 2026-01-01..2026-09-30，或无法解析）。全集在 `anomalies.json`，按 order_id 升序、同号按规则名升序。示例每类至多 3 条。

| 规则 | 条数 |
|------|------|
| A1 amount<10.00 | 5 |
| A2 cancelled 且 amount>1000.00 | 105 |
| A3 order_id 重复 | 0 |
| A4 日期越界 | 0 |

### A1 示例

- order_id=1967 customer_id=C0223 order_date=2026-02-12 amount=7.46 status=pending channel=app
- order_id=2471 customer_id=C0454 order_date=2026-01-18 amount=6.12 status=paid channel=app
- order_id=3322 customer_id=C0180 order_date=2026-07-07 amount=5.34 status=paid channel=web

### A2 示例

- order_id=2 customer_id=C0568 order_date=2026-01-08 amount=1443.49 status=cancelled channel=store
- order_id=44 customer_id=C0670 order_date=2026-07-17 amount=1545.01 status=cancelled channel=app
- order_id=160 customer_id=C0379 order_date=2026-06-01 amount=1996.19 status=cancelled channel=web

### A3 示例

无

### A4 示例

无
