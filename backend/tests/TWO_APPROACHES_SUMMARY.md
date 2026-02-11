# 两种修复路径总结：Skew 校正 vs Block Pairing

## 当前架构回顾

```
blocks (OCR) 
  → TextBlock (Step 0)
  → _wash_blocks (Step 0b)
  → build_physical_rows (Step 1)     ← 按 Y 聚类，核心依赖坐标
  → detect_amount_columns (Step 2)
  → split_regions (Step 3)           ← 依赖 PhysicalRow
  → extract_items (Step 4)           ← 遍历 item_rows，按 amount 找 name（Y 窗口、left_blocks）
  → find_subtotal_and_total, ...
```

**核心假设**：`build_physical_rows` 用 `center_y` 的差值判断「是否同一行」。Skew 会导致本应同一行的 block 因 Y 不同而被拆成多行或错行。

---

## 思路 1：Skew 校正（改动最小）✓ 主路径

### 定位
在**现有 pipeline 前**加一层**纯坐标变换**，不改任何下游逻辑。

### 改动范围

| 模块 | 改动 |
|------|------|
| **新建** `skew_corrector.py` | ~80–120 行 |
| `receipt_pipeline_v2.py` | 插入 1 行 |

### 具体改动

1. **新建 `skew_corrector.py`**
   - `correct_skew(text_blocks, store_config?) -> List[TextBlock]`
   - 逻辑：
     - 用 store_config 或 pattern 找到参考行（如 T&T：`01/25/26 12:46:58 PM` + `MeiChen`）
     - 取该行最左、最右 block 的 `(x, y)`，计算倾斜角 θ = atan2(Δy, Δx)
     - 对所有 block 做旋转变换：`(x', y') = rotate((x, y), -θ)`
     - 更新 `TextBlock` 的 `x, y, center_x, center_y`（若有 `width/height` 需一并处理）
   - 置信度检查：若倾斜角异常或参考行缺失 → 不校正，原样返回
   - 可选：fold 检测（多行倾斜角方差大）→ 不校正

2. **修改 `receipt_pipeline_v2.py`**
   - 在 Step 0b 之后、Step 1 之前插入：
   ```python
   # Step 0c: Optional skew correction (T&T reference line)
   text_blocks = correct_skew(text_blocks, store_config)
   ```

3. **store_config 扩展（可选）**
   - 如 `reference_line_pattern` 或 `skew_reference_markers` 用于定位参考行

### 不动的部分
- `row_reconstructor.py`：不改
- `item_extractor_v2.py`：不改
- `region_splitter.py`：不改
- 其他模块：不改

### 风险
- 参考行识别错误 → 误校正
- 折叠/卷曲小票 → 全局校正可能恶化，需通过置信度检查跳过

---

## 思路 2：Block Pairing（改动较大）— Backup

### 定位
引入**新的 item 提取范式**：左侧按结构解析出 n 个 item，右侧按顺序取 n 个金额，1:1 配对。

### 改动范围

| 模块 | 改动 |
|------|------|
| **新建** `block_pairing_extractor.py` | ~250–350 行 |
| `receipt_pipeline_v2.py` | 增加 fallback 分支（约 10–15 行） |
| 可能涉及 `receipt_structures.py` | 若需新结构体 |

### 具体改动

1. **新建 `block_pairing_extractor.py`**
   - `extract_items_block_pairing(regions, amount_columns, store_config) -> List[ExtractedItem]`
   - 流程：
     - 从 `regions.item_rows` 收集 blocks，按 `center_y` 排序
     - 用 `_detect_left_right_boundary` 得到 X 边界
     - **左侧解析**：
       - 过滤 `center_x < boundary`，按 Y 排序
       - 遍历：section header → 跳过；全大写名称 → 新 item；`x lb @ $y/lb` 或 `n @ $y` → 附属上一 item 的 qty/unit；`tare removed` 等 note → 跳过
       - 得到 `left_items: List[Tuple[name, qty?, unit?, unit_price?]]`
     - **右侧解析**：
       - 过滤 `center_x >= boundary`、`is_amount`，排除 Points $0.00 等，按 Y 排序
       - 得到 `right_amounts: List[float]`
     - **1:1 配对**：`len(left_items) == len(right_amounts)` 时配对；不等时需策略（如截断或报错）
   - 复用：`_apply_product_name_cleanup`, `_extract_qty_and_price`, `SECTION_HEADERS` 等，可从 `item_extractor_v2` 抽成共用 util 或直接 import

2. **修改 `receipt_pipeline_v2.py`**
   - 在 Step 4 后、Step 7 校验后：
   ```python
   if not totals_valid and store_config:
       items_backup = extract_items_block_pairing(regions, amount_columns, store_config)
       # 重新校验，若通过则用 items_backup 替换 items
   ```

3. **与 AmountUsageTracker 的配合**
   - Block pairing 不按 row 使用 tracker，需决定：是否在 fallback 路径跳过 tracker，或为 block pairing 单独实现一套 usage 逻辑

### 难点
- Section header 无金额：左侧有 PRODUCE、DELI，右侧金额要与之错位配对
- 多行 item（name + qty/unit 两行）：左侧聚合逻辑要处理好
- `n_left != n_right`：需明确处理策略

### 依赖
- 仍依赖 `build_physical_rows` 和 `split_regions` 得到 `item_rows`（或需额外实现基于 Y 的 item 区域划分）

---

## 对比

| 维度 | 思路 1 Skew 校正 | 思路 2 Block Pairing |
|------|------------------|----------------------|
| **新增代码量** | ~100 行 | ~300 行 |
| **改动文件数** | 1 新建 + 1 修改 | 1 新建 + 1 修改 |
| **下游影响** | 无 | 需 fallback 分支 |
| **与现有逻辑关系** | 仅预处理，完全解耦 | 新 extractor，与现有并存 |
| **适用场景** | 整体倾斜 | 折痕、卷曲、Y 错位严重 |

---

## 建议顺序

1. **主路径**：实现思路 1（Skew 校正）
2. **备份路径**：实现思路 2（Block Pairing），仅在主路径校验失败时启用
