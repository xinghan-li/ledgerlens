# 小票处理流程说明

## 流程顺序

1. **OCR blocks** → 原始文本块（每个块有 x, y, center_x, center_y, text）
2. **skew_corrector** → 校正倾斜（date+收银员参考）
3. **row_reconstructor** → 按 Y 坐标把 blocks 聚合成 PhysicalRow
4. **region_splitter** → 分出 header / items / totals
5. **item_extractor** → 遍历 item_rows，对每行的每个 amount 找左侧品名

## 「amount-only 行」从哪来的

**不是业务概念**，是 row_reconstructor 分组过严产生的**错误拆分**。

### 实际情况（小票物理布局）

```
JAPANESE SWEET POTATO  /lb                    FP $1.83     ← 同一行
0.92 lb @ $1.99        0.92
```

JSP 和 $1.83 本应是同一行。

### 当前实现发生了什么

1. **skew 校正后**：JSP cy=0.5763，FP $1.83 cy=0.5862，差 0.0098
2. **row_reconstructor**：eps = min(half_height, **MAX_ROW_HEIGHT_EPS=0.008**)，0.0098 > 0.008 → 分成两行
3. 实际得到：
   - Row 10: [JSP, /lb]（只有左侧）
   - Row 11: [FP $1.83]（只有右侧）← 被当成「amount-only」
   - Row 12: [0.92 lb, 0.92]

4. **item_extractor**：按行遍历，到 Row 11 时，`left_blocks_in_row` 为空（该行只有 amount），于是 skip。

### 结论

- 小票上**不存在**「只有金额、没有品名」的行。
- 我们看到的「amount-only」是因为 **row_reconstructor 把 JSP 和 $1.83 拆成了两行**。
- 正确做法：调整 row_reconstructor，让 JSP 和 $1.83 保留在同一行，而不是在 item_extractor 里做 amount-only 恢复。
