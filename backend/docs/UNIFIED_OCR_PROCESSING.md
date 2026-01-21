# 统一的 OCR 处理架构

## 问题背景

之前的设计中，每个 OCR 服务（Google Document AI、AWS Textract）都需要：
- 单独的提取逻辑
- 单独的验证逻辑
- 商店特定的规则需要为每个 OCR 重复实现

这导致工作量翻倍，且难以维护。

## 解决方案：统一标准化架构

### 核心思想

1. **统一标准化层**：所有 OCR 输出先标准化为统一格式
2. **基于 raw_text 的统一提取**：不管 OCR 来源，都从 `raw_text` 提取（所有 OCR 都有 `raw_text`）
3. **统一的验证逻辑**：所有验证都基于标准化后的数据
4. **商店特定的规则只需一套**：针对 `raw_text` 格式，不针对 OCR

### 架构图

```
┌─────────────────┐     ┌─────────────────┐
│ Google Document │     │  AWS Textract   │
│      AI         │     │                 │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
         ┌───────────▼───────────┐
         │   OCR Normalizer      │
         │  (标准化为统一格式)    │
         └───────────┬───────────┘
                     │
         ┌───────────▼───────────┐
         │  Unified Format       │
         │  - raw_text           │
         │  - entities           │
         │  - line_items         │
         │  - metadata           │
         └───────────┬───────────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼────┐    ┌─────▼─────┐   ┌─────▼──────┐
│基于    │    │基于        │   │统一        │
│raw_text│    │标准化数据  │   │验证逻辑    │
│提取    │    │LLM处理     │   │            │
│价格    │    │            │   │            │
└────────┘    └────────────┘   └────────────┘
```

## 统一格式（Unified OCR Result Format）

```json
{
    "raw_text": "string",  // 所有 OCR 都有
    "merchant_name": "string | null",
    "entities": {
        "merchant_name": {"value": "string", "confidence": 0.0-1.0},
        "total_amount": {"value": "string", "confidence": 0.0-1.0},
        ...
    },
    "line_items": [
        {
            "raw_text": "string",
            "product_name": "string | null",
            "quantity": "number | null",
            "unit": "string | null",
            "unit_price": "number | null",
            "line_total": "number | null",
            "is_on_sale": "boolean",
            "category": "string | null"
        }
    ],
    "metadata": {
        "ocr_provider": "google_documentai" | "aws_textract" | "google_vision",
        "original_data": {}  // 保留原始数据供调试
    }
}
```

## 关键函数

### 1. `normalize_ocr_result(ocr_result, provider)`

将不同 OCR 的输出标准化为统一格式。

**支持的提供商：**
- `google_documentai`
- `aws_textract`
- `google_vision`

**自动检测：** 如果没有指定 provider，会根据数据结构自动检测。

### 2. `process_receipt_with_llm_from_ocr(ocr_result, merchant_name, ocr_provider)`

统一的 LLM 处理函数，接受任何标准化后的 OCR 结果。

**优势：**
- 自动标准化（如果还没标准化）
- 基于 `raw_text` 的统一提取
- 统一的验证逻辑
- 商店特定的规则只需一套

### 3. `extract_line_totals_from_raw_text(raw_text, docai_line_items, merchant_name)`

**关键优势：** 这个函数已经基于 `raw_text`，可以用于任何 OCR！

**工作流程：**
1. 优先使用 OCR 提供的 `line_items`（如果有）
2. Fallback 到基于 `raw_text` 的正则表达式提取（使用商店特定的规则）

## 使用示例

### 示例 1：使用 Google Document AI

```python
# 1. 调用 Document AI
docai_result = parse_receipt_documentai(image_bytes, mime_type="image/jpeg")

# 2. 直接调用统一处理函数（自动标准化）
result = process_receipt_with_llm_from_ocr(
    ocr_result=docai_result,
    ocr_provider="google_documentai"
)
```

### 示例 2：使用 AWS Textract

```python
# 1. 调用 Textract
textract_result = parse_receipt_textract(image_bytes)

# 2. 直接调用统一处理函数（自动标准化）
result = process_receipt_with_llm_from_ocr(
    ocr_result=textract_result,
    ocr_provider="aws_textract"
)
```

### 示例 3：API 端点使用

```bash
# 1. 调用 OCR 端点
curl -X POST "http://localhost:8000/api/receipt/amzn-ocr" \
  -F "file=@receipt.jpg"

# 返回：
# {
#   "filename": "receipt.jpg",
#   "success": true,
#   "data": {
#     "raw_text": "...",
#     "entities": {...},
#     "line_items": [...],
#     "metadata": {"ocr_provider": "aws_textract"}
#   }
# }

# 2. 调用 LLM 处理（自动检测 OCR 提供商）
curl -X POST "http://localhost:8000/api/receipt/llm-process" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "receipt.jpg",
    "data": {
      "raw_text": "...",
      "entities": {...},
      ...
    }
  }'
```

## 优势总结

### 1. 避免重复工作
- ✅ 提取逻辑只需一套（基于 `raw_text`）
- ✅ 验证逻辑只需一套（统一格式）
- ✅ 商店特定的规则只需一套（针对 `raw_text`）

### 2. 易于扩展
- ✅ 添加新的 OCR 服务只需实现 `normalize_ocr_result` 中的标准化函数
- ✅ 所有后续处理（提取、验证、LLM）自动支持新 OCR

### 3. 统一的验证
- ✅ 不管 OCR 来源，验证逻辑一致
- ✅ 基于 `raw_text` 的提取确保可靠性

### 4. 商店特定规则
- ✅ 规则针对 `raw_text` 格式（如 "FP $X.XX"），不针对 OCR
- ✅ 一套规则适用于所有 OCR

## 未来改进

### 多 OCR 对比验证

可以使用两个 OCR 的结果进行对比验证：

```python
# 1. 调用两个 OCR
docai_result = parse_receipt_documentai(image_bytes)
textract_result = parse_receipt_textract(image_bytes)

# 2. 标准化
docai_normalized = normalize_ocr_result(docai_result, "google_documentai")
textract_normalized = normalize_ocr_result(textract_result, "aws_textract")

# 3. 对比 raw_text 和提取的价格
# 如果两个 OCR 的 raw_text 差异大，或提取的价格总和差异大，标记为需要人工审核

# 4. 选择更可靠的结果或合并结果
```

### 置信度加权

不同 OCR 对不同字段的置信度可能不同，可以：
- 对比两个 OCR 的 `entities` 置信度
- 选择置信度更高的字段
- 对于冲突的字段，标记在 `tbd.field_conflicts` 中

## 相关文件

- `backend/app/ocr_normalizer.py` - OCR 标准化器
- `backend/app/receipt_llm_processor.py` - 统一的 LLM 处理函数
- `backend/app/extraction_rule_manager.py` - 商店特定的提取规则（基于 raw_text）
- `backend/app/main.py` - API 端点（支持自动检测 OCR 提供商）
