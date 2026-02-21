# 20260209_121422 小票 Debug 诊断报告

## Debug 结论

通过添加 `[left_blocks]` 和 `[qty/unit]` 日志，确认：

1. **GOLDEN DEW PEAR / JAPANESE SWEET POTATO** 的 qty/unit 提取**已正确**：
   - left_blocks 正确包含了 "2.68 lb @ $2.88/1b" 和 "0.92 lb @ $1.99"
   - _extract_qty_and_price 成功解析

2. **问题 1 (已修复): 重量 quantity 输出 26800 而非 268**
   - **根因**: item_extractor 存了 `268`（百分制），pipeline 输出又乘 100 → 26800
   - **修复**: 重量商品存**基础单位** (2.68)，由输出层做 `int(round(qty*100))`

3. **问题 2: GYG NINGBO line_total=2053**
   - Row 16: GYG + $0.00（积分兑换后），Row 18: $20.53 (TOTAL)
   - 金额列检测将 $20.53 误关联到 GYG → 需在 totals 前排除 TOTAL 金额

4. **问题 3: AFC SOYMILK 重复**
   - Row 14: DELI + FP $4.99，Row 15: AFC + FP $5.99
   - OCR 行合并导致 $4.99 和 $5.99 都匹配到 AFC

5. **问题 4 (已修复): "JAPANESE SWEET POTATO /lb"**
   - OCR 将 "/lb" 识别为独立 block，已加 strip 清理
