# LLM 收据处理系统文档

## 架构概述

本系统实现了 **Document AI + LLM** 的混合架构，用于高精度收据解析：

```
图片上传
    ↓
Document AI (提取 raw_text + entities)
    ↓
提取高置信度字段 (confidence >= 0.95) → trusted_hints
    ↓
根据 merchant_name 获取 RAG prompt
    ↓
OpenAI LLM (结构化重建 + 验证)
    ↓
返回结构化 JSON (可直接存数据库)
```

## 核心组件

### 1. `prompt_manager.py`
- 管理商店特定的 RAG prompts
- 从 Supabase `merchant_prompts` 表加载 prompts
- 提供默认 prompt 作为 fallback
- 支持 prompt 缓存

### 2. `llm_client.py`
- OpenAI API 客户端封装
- 强制 JSON 输出格式
- 错误处理和日志记录

### 3. `receipt_llm_processor.py`
- 整合完整流程
- 提取 trusted_hints
- 调用 LLM 进行结构化重建

## 数据库设置

### 1. 创建 merchant_prompts 表

```sql
-- 运行 database/002_merchant_prompts.sql
```

### 2. 插入示例 Prompt

```sql
-- 运行 database/003_insert_example_prompt.sql
-- 记得修改 merchant_id 为实际的商户 ID
```

## 配置

在 `.env` 文件中添加：

```env
# OpenAI Configuration
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_MODEL=gpt-4o-mini  # 可选，默认 gpt-4o-mini
```

## API 端点

### POST `/api/receipt/llm-process`

完整的 Document AI + LLM 处理流程。

**请求：**
- Content-Type: `multipart/form-data`
- 参数：`file` (图片文件)

**响应：**
```json
{
  "filename": "receipt.jpg",
  "success": true,
  "data": {
    "receipt": {
      "merchant_name": "T&T Supermarket",
      "merchant_address": "...",
      "purchase_date": "2026-01-10",
      "purchase_time": "14:47:15",
      "subtotal": 22.77,
      "tax": 0.0,
      "total": 22.77,
      "payment_method": "Visa",
      "card_last4": "9463"
    },
    "items": [
      {
        "raw_text": "GREEN ONION\nFP $1.29",
        "product_name": "GREEN ONION",
        "line_total": 1.29,
        "is_on_sale": false
      },
      ...
    ],
    "tbd": {
      "items_with_inconsistent_price": [],
      "field_conflicts": {},
      "missing_info": []
    },
    "_metadata": {
      "merchant_name": "T&T Supermarket",
      "merchant_id": 1,
      "validation_status": "pass"
    }
  }
}
```

## 管理 Merchant Prompts

### 添加新的 Merchant Prompt

```sql
INSERT INTO merchant_prompts (
  merchant_id,
  merchant_name,
  prompt_template,
  system_message,
  model_name,
  temperature,
  output_schema,
  is_active
) VALUES (
  1,  -- merchant_id
  'Your Merchant Name',
  'Your custom prompt template with {raw_text}, {trusted_hints}, {output_schema} placeholders',
  'Your system message',
  'gpt-4o-mini',
  0.0,
  '{"receipt": {...}, "items": [...], "tbd": {...}}'::jsonb,
  true
);
```

### 更新现有 Prompt

```sql
UPDATE merchant_prompts
SET 
  prompt_template = 'New template...',
  updated_at = now()
WHERE merchant_id = 1 AND is_active = true;
```

### 禁用 Prompt（使用默认）

```sql
UPDATE merchant_prompts
SET is_active = false
WHERE merchant_id = 1;
```

## Prompt 模板变量

Prompt 模板支持以下占位符：

- `{raw_text}`: 原始收据文本（来自 Document AI）
- `{trusted_hints}`: 高置信度字段的 JSON（confidence >= 0.95）
- `{output_schema}`: 输出 JSON schema 定义

## Trusted Hints 结构

```json
{
  "merchant_name": {
    "value": "T&T Supermarket",
    "confidence": 1.0,
    "source": "documentai"
  },
  "total": {
    "value": "22.77",
    "confidence": 0.76,
    "source": "documentai"
  },
  ...
}
```

## 输出 Schema

标准输出包含：

1. **receipt**: 收据级别信息
   - merchant_name, address, phone
   - purchase_date, purchase_time
   - subtotal, tax, total
   - payment_method, card_last4

2. **items**: 商品列表
   - raw_text, product_name
   - quantity, unit, unit_price, line_total
   - is_on_sale, category

3. **tbd**: 待确认/问题项
   - items_with_inconsistent_price
   - field_conflicts
   - missing_info

## 验证逻辑

LLM 会自动执行以下验证：

1. **单价验证**: `quantity × unit_price ≈ line_total` (±0.01)
2. **总计验证**: `sum(line_totals) ≈ total` (±0.01)
3. **冲突检测**: raw_text vs trusted_hints

验证失败的项目会记录在 `tbd` 中。

## 最佳实践

1. **Prompt 设计**:
   - 明确给出 JSON schema
   - 包含商店特定的格式说明
   - 强调验证要求

2. **Confidence 阈值**:
   - 默认 0.95（只使用高置信度字段）
   - 可根据需要调整

3. **错误处理**:
   - 检查 `tbd` 字段
   - 对于需要人工确认的项目，在前端显示

4. **成本优化**:
   - 使用 `gpt-4o-mini` 作为默认模型（更便宜）
   - 对于复杂收据，可以升级到 `gpt-4o`

## 故障排查

### LLM 返回非 JSON

- 检查 `response_format={"type": "json_object"}` 是否设置
- 确保 prompt 中明确要求 JSON 输出

### Prompt 未找到

- 检查 `merchant_prompts` 表中是否有对应记录
- 检查 `is_active = true`
- 系统会自动 fallback 到默认 prompt

### 验证失败

- 检查 `tbd` 字段中的详细信息
- 可能需要调整 prompt 中的验证逻辑说明
