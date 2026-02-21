# Classification Review 表格更新 - 2026-02-17

## 已实现

### 1. Category 拆成三列 (Category I, II, III)
- 前端：级联下拉，先选 L1 → L2 → L3，仅 L3 选择后 PATCH category_id
- 表结构未改：仍用 category_id (L3) 存储，L1/L2 由 categories 树推导

### 2. LLM 预填分类
- Migration 026：在 prompt_library 新增 key=`classification` 的 system prompt
- `classification_llm.py`：调用 Gemini，输入 raw_product_names + store_chain_name，输出 category (L1/L2/L3)、size、unit_type
- 在 `enqueue_unmatched_items_to_classification_review` 中，入队前调用 LLM 建议，将 category_id/size/unit_type 预填进 classification_review

### 3. Status 下拉移除 confirmed
- 行内 status 下拉不再包含 `confirmed`，只能通过右侧 Confirm 按钮设为 confirmed

### 4. Size / Unit Type
- 直接写入 classification_review.size、unit_type（TEXT），confirm 时写入 products 表
- 前端：size、unit_type 列为文本输入框（blur 时 PATCH）

### 5. confirmed_at / confirmed_by
- 后端：确认时写入 `confirmed_at` (ISO)、`confirmed_by` (user_id)
- 前端：表格增加 confirmed_at、confirmed_by 列显示

## 待执行 Migration

```bash
# 在 Supabase SQL Editor 或迁移脚本中执行：
# 026_add_classification_prompt.sql
# 028_categories_lowercase.sql
```

## Gemini 模型

可通过环境变量 `GEMINI_MODEL` 指定模型，例如 `gemini-2.5-flash` 或 `gemini-2.0-flash-exp`。
