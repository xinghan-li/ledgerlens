# Receipt Processing Pipeline V2

## 架构概览

新的 pipeline 采用**以行为中心**的架构，替代了之前"以金额为中心"的局部规则方法。

## 核心模块

### Step 0: 数据结构定义 (`receipt_structures.py`)
- `TextBlock`: OCR 文本块
- `PhysicalRow`: 物理行（包含多个 TextBlock）
- `ReceiptRegions`: 分区结果（header/item/totals/payment rows）
- `AmountColumns`: 检测到的金额列
- `AmountUsageTracker`: 金额使用追踪器（消消乐逻辑）
- `ExtractedItem`: 提取的商品项
- `TotalsSequence`: 总额序列

### Step 1: 物理行重建 (`row_reconstructor.py`)
- 按 Y 坐标聚类形成 `PhysicalRow`
- 解决折行商品名等问题
- 使用 `row_height_eps` 阈值（默认 0.005）

### Step 2: 统计学列检测 (`column_detector.py`)
- 对所有金额的 X 坐标做直方图
- 找到主金额列（通常是右对齐的列）
- 不依赖 subtotal 的 X 坐标作为 anchor

### Step 3: 区域划分 (`region_splitter.py`)
- 使用硬特征确定分界：
  - SUBTOTAL 标记 → items 和 totals 的分界
  - Payment 标记（Visa, Mastercard 等）→ totals 和 payment 的分界
- 每个 row 的 `row_type` 自动更新

### Step 4: Item 提取 (`item_extractor_v2.py`)
- 在 `item_rows` 中查找金额
- 支持多行商品名（回看上一行）
- 使用 `AmountUsageTracker` 标记已使用的金额

### Step 5: Totals 序列提取 (`totals_extractor.py`)
- 在 `totals_rows` 中查找 subtotal 和 total
- 收集 subtotal 和 total 之间的 middle amounts
- 排除已使用的金额块

### Step 6: 税费识别 (`tax_fee_classifier.py`)
- 使用 fuzzy matching 分类税费
- 优先级：explicit tax > generic fee/tax
- 验证 tax < 20% of subtotal

### Step 7: 数学校验 (`math_validator.py`)
- 行级校验：qty × unit_price = line_total
- 总体校验：items sum = subtotal, subtotal + fees + tax = total

### Step 8: 金额唯一使用约束
- `AmountUsageTracker` 使用 block_id 和 Y 坐标追踪
- 每个金额只能使用一次
- 详细的 usage log 用于调试

### Step 9: 错误处理与调试输出
- 详细的日志输出
- Usage tracker 摘要
- 格式化的垂直加法输出

## API 端点

### `/api/receipt/initial-parse`
新的 pipeline 端点，返回：
- `success`: 验证是否通过
- `items`: 提取的商品列表
- `totals`: Subtotal, tax, fees, total
- `validation`: 验证结果详情
- `usage_tracker`: 金额使用摘要
- `formatted_output`: 格式化的调试输出

## 关键改进

1. **区域隔离**: Items 和 Totals 在 Y 轴上严格切割，避免 item 金额混入 totals
2. **消消乐逻辑**: 使用 block_id 和 Y 坐标作为唯一 ID，确保每个金额只使用一次
3. **列检测**: 统计学方法检测金额列，不依赖 subtotal 位置
4. **多行支持**: 支持折行的商品名
5. **Tax 验证**: Tax 必须 < 20% of subtotal
6. **数学校验**: 行级和总体双重校验

## 使用方式

```python
from .processors.validation.receipt_pipeline_v2 import process_receipt_pipeline

result = process_receipt_pipeline(blocks, llm_result)
```

## 迁移计划

旧的 `coordinate_based_sum_check` 函数仍然保留，新的 pipeline 通过 `/api/receipt/initial-parse` 端点访问。

未来可以逐步迁移到新 pipeline，或让两个版本并行运行以对比效果。
