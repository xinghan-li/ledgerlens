# 小票提取逻辑诊断报告

## 1. DELI / $4.99 / AFC / $5.99 的 Y 偏移量

| Block | Y 坐标 | 
|-------|--------|
| DELI | 0.6279 |
| $4.99 | 0.6203 |
| AFC SOYMILK | 0.6328 |
| $5.99 | 0.6365 |

**偏移量（与 half_line=0.0116 对比）：**
- **$4.99 到 AFC**：0.0125，约 **1.07 × half_line**（略大于半行）
- **$5.99 到 AFC**：0.0036，约 **0.31 × half_line**（远小于半行）

**结论**：按 Y 距离，$5.99 离 AFC 更近；$4.99 离 AFC 略超半行。用户说的「section header 行右边默认无数值、$4.99 应对应 AFC」是指：在 DELI 分区下，第一个金额 $4.99 应归属第一个商品 AFC，而不是 DELI。

## 2. 正确的业务逻辑（用户期望）

- 当行左侧**只有** DELI/PRODUCE/MEAT 等 section header 时，该行右侧的金额**不属于** section header，而属于**下一行的第一个商品**。
- 因此：Row 14 (DELI + $4.99) → $4.99 应归 AFC SOYMILK，不是跳过。
- 当前错误修复：直接 skip 了 $4.99，导致 AFC 少了一笔金额。

## 3. GYG 为何匹配到 $20.53？

**根本原因**：Row 18 只包含 $20.53，却被分进了 **item_rows**，而不是 totals_rows。

```
Row 18: 只有 "$20.53"，无左侧文字 → 在 item_rows 中
Row 19: "TOTAL $20.53" → 在 totals_rows 中
```

**Region split 逻辑**：切换到 TOTALS 的条件是行内出现 "TOTAL" 等关键词。Row 18 只有 "$20.53"，没有 "TOTAL"，因此仍被当作 ITEM 行。

**Item 提取逻辑**：处理 Row 18 时，行内无商品名，会向上查找 name。`_full_product_name_above_amount` 在 left_blocks 中向上扫，找到最近的 all-caps 品名 → **GYG NINGBO**，于是错误地把 $20.53 归到 GYG。

**$20.53 到 GYG 的 Y 距离**：0.0378，约 **3.25 × half_line**，明显不是同一行，但当前逻辑不检查 section，只按「最近的 name 在上方」来匹配。

## 4. 编程逻辑错误总结

| 问题 | 错误逻辑 | 正确逻辑 |
|------|----------|----------|
| Section header + 金额 | 当成无效行直接 skip | 金额应归属**下一行第一个商品** |
| 仅金额行 (如 $20.53) | 被分到 item_rows，向上抓 name → 误匹配 GYG | 应归入 totals 或排除出 item 提取；不应向上抓 name |
| Region split | 仅看行内是否有 "TOTAL" | 仅有金额、无左侧文字且可能是 total 的行，应归 totals 或单独处理 |

## 5. 已实施修复

1. **Section header 行 + 金额**：将金额关联到**下一行**第一个商品（如 DELI + $4.99 → AFC SOYMILK）。若上一笔已用本行品名，则本行金额归属**再下一行**商品（如 AFC 行 $5.99 → GYG）。
2. **Row 仅有金额（无左侧文字）**：禁止向上查找 name，直接 skip（如 lone $20.53 不再误匹配 GYG）。
