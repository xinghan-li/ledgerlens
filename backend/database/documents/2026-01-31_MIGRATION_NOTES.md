# 2026-01-31 Migration Notes

本文档记录所有数据插入和内容迁移操作。这些操作不改变数据库结构，只填充数据。

**重要说明**：
- 所有数据插入操作应通过 RAG 管理 API (`/api/rag/*`) 或初始化脚本 (`backend/scripts/init_deposit_fee_rag.py`) 完成
- 本文档的描述足够详细，可以让 LLM 无歧义地生成对应的 SQL 语句
- 如果需要在新的数据库环境中初始化，请使用 API 或脚本，而不是直接运行 SQL

---

## 一、初始商店数据 (002_insert_initial_data.sql)

### 1.1 Store Chains 数据

需要插入以下商店连锁到 `store_chains` 表：

| name | normalized_name | aliases | is_active |
|------|----------------|---------|-----------|
| T&T Supermarket | t&t supermarket | ['T&T Supermarket US', 'T&T Supermarket US Lynnwood Store', 'TNT Supermarket', 'T & T', 'TNT'] | true |
| T&T Supermarket Canada | t&t supermarket canada | ['T&T Supermarket Osaka Store', 'TNT Supermarket - Osaka Branch', 'T&T Osaka', 'TNT'] | true |
| Trader Joe's | trader joe's | ['Trader Joes', 'TJs', 'TRADER'] | true |
| 99 Ranch Market | 99 ranch market | ['99 Ranch', 'Ranch 99'] | true |
| In-N-Out Burger | in-n-out burger | ['In N Out', 'In-N-Out', 'INO', 'In N Out Burger'] | true |

**SQL 模板**：
```sql
INSERT INTO store_chains (name, normalized_name, aliases, is_active)
VALUES (
  '{name}',
  '{normalized_name}',
  ARRAY[{aliases}],
  true
)
ON CONFLICT (normalized_name) DO NOTHING;
```

**注意**：
- `normalized_name` 必须是唯一的（有 UNIQUE 约束）
- `aliases` 是 PostgreSQL 数组类型，格式为 `ARRAY['alias1', 'alias2']`
- 使用 `ON CONFLICT DO NOTHING` 避免重复插入

---

## 二、Tag-based RAG 系统初始数据 (009_tag_based_rag_system.sql 中的数据部分)

### 2.1 T&T Supermarket Tag

**Tag 定义**：
- `tag_name`: `'t&t'`
- `tag_type`: `'store'`
- `description`: `'T&T Supermarket specific parsing rules and formats'`
- `priority`: `100`
- `is_active`: `true`

**Snippets**：

1. **System Message Snippet** (如果从 `store_chain_prompts` 迁移)：
   - `snippet_type`: `'system_message'`
   - `content`: 从 `store_chain_prompts` 表的 `system_message` 字段提取（如果存在）
   - `priority`: `10`
   - `is_active`: `true`

2. **Prompt Addition Snippet**：
   - `snippet_type`: `'prompt_addition'`
   - `content`: 
     ```
     ## T&T Supermarket Specific Notes:
     - Items are often listed with "FP" (Final Price) prefix
     - Weight-based items show format: "X.XX lb @ $X.XX/lb FP $X.XX"
     - Sale items are marked with "(SALE)" prefix
     - Categories: FOOD, PRODUCE, DELI, GROCERY, etc.
     - Items may span multiple lines (product name on one line, price on next)
     - Look for "FP $X.XX" pattern for line totals
     - Ignore lines with "Points XX $0.00" (these are loyalty points, not products)
     - Ignore lines with membership card numbers (e.g., "***600032371" or "会员卡 1234567890123") that have $0.00
     - If you see membership card number, extract it to a separate "membership_number" field in the receipt object
     
     ## Address Parsing:
     - If address contains "Suite", "Ste", "Unit", "Apt", "#" followed by a number, split into address_line1 and address_line2
     - Canadian format: "#1000-3700 No.3 Rd." should be parsed as address_line1="3700 No.3 Rd" and address_line2="#1000"
     - If address ends with a comma followed by "Suite", "Unit", etc., the part after comma is address_line2
     
     ## Tax and Subtotal:
     - Extract subtotal and tax ONLY if explicitly stated on the receipt
     - Set them to null if not shown
     - Do NOT calculate or estimate tax by subtracting subtotal from total
     - Deposits, fees, and other charges are NOT tax (e.g., "Bottle deposit", "Env fee")
     ```
   - `priority`: `10`
   - `is_active`: `true`

3. **Extraction Rules Snippet** (如果从 `store_chain_prompts` 迁移)：
   - `snippet_type`: `'extraction_rule'`
   - `content`: 从 `store_chain_prompts` 表的 `extraction_rules` 字段提取（如果存在，转换为 TEXT）
   - `priority`: `10`
   - `is_active`: `true`

**Matching Rules**：
- `match_type`: `'fuzzy_store_name'`, `match_pattern`: `'t&t'`, `priority`: `100`
- `match_type`: `'fuzzy_store_name'`, `match_pattern`: `'tnt'`, `priority`: `100`
- `match_type`: `'fuzzy_store_name'`, `match_pattern`: `'t & t'`, `priority`: `100`
- `match_type`: `'keyword'`, `match_pattern`: `'t&t supermarket'`, `priority`: `90`
- `match_type`: `'keyword'`, `match_pattern`: `'tnt supermarket'`, `priority`: `90`

---

### 2.2 Package Price Discount Tag

**Tag 定义**：
- `tag_name`: `'package_price_discount'`
- `tag_type`: `'discount_pattern'`
- `description`: `'Package price discounts (e.g., "2/$9.00", "3 for $10", "Buy 2 Get 1")'`
- `priority`: `80`
- `is_active`: `true`

**Snippets**：

1. **System Message Snippet**：
   - `snippet_type`: `'system_message'`
   - `content`: 
     ```
     You are a receipt parsing expert. When you encounter package price discounts (e.g., "2/$9.00", "3 for $10", "Buy 2 Get 1"), you must:
     1. Extract the ACTUAL line_total from the receipt, NOT the calculated quantity × unit_price
     2. Do NOT "correct" line_total values for package discounts - use the actual values from the receipt
     3. If you see "2/$9.00" and the receipt shows two items with line_totals that sum to $9.00, this is correct
     4. Mark is_on_sale = true for items that are part of package deals
     5. CRITICAL: For package discounts, line_total may be LESS than quantity × unit_price - this is EXPECTED and CORRECT
     6. Do NOT add items to items_with_inconsistent_price for package discounts - the discount is the reason for the difference
     ```
   - `priority`: `10`
   - `is_active`: `true`

2. **Prompt Addition Snippet**：
   - `snippet_type`: `'prompt_addition'`
   - `content`: 
     ```
     ## Package Price Discounts (CRITICAL - READ CAREFULLY):
     
     When you see patterns like:
     - "2/$9.00" or "2 for $9.00" (buy 2 items for $9.00 total)
     - "3/$10" or "3 for $10" (buy 3 items for $10.00 total)
     - "Buy 2 Get 1" (buy 2, get 1 free)
     - "discount" or "sale" with quantity/price patterns
     - Similar package deals
     
     **CRITICAL RULES (DO NOT VIOLATE):**
     1. **DO NOT validate quantity × unit_price = line_total for package discounts** - this check is DISABLED for items in package deals
     2. The line_total for individual items in a package deal may be LESS than quantity × unit_price - this is EXPECTED
     3. ALWAYS use the ACTUAL line_total shown on the receipt, NOT the calculated quantity × unit_price
     4. **Example 1**: If receipt shows "1 @ $4.99 each (2/$9.00)" and the actual line_total printed is $4.01, use $4.01, NOT $4.99
     5. **Example 2**: If receipt shows "2/$9.00" and you find 2 items with line_totals of $4.99 and $4.01 (sum = $9.00), this is CORRECT - do not "fix" either price
     6. **Example 3**: If unit_price shows $4.99 but line_total shows $4.01, and there is a "2/$9.00" discount, use $4.01 as line_total
     7. Mark is_on_sale = true for items that are part of package deals
     8. **DO NOT add items to items_with_inconsistent_price for package discounts** - the discount is the reason for the difference, not an error
     
     **How to Identify Package Discounts:**
     - Look for patterns: "2/$", "3 for $", "Buy X Get Y", "discount", "sale" near price information
     - Check if multiple items have the same or similar product name
     - Verify if their line_totals sum to a round number (e.g., $9.00, $10.00) that matches the discount pattern
     
     **Validation (for your reference, not for flagging errors):**
     - If you see "2/$9.00" pattern, verify that:
       * There are 2 items with the same or similar product name
       * Their line_totals sum to approximately $9.00 (tolerance: ±0.03)
       * If this validation passes, the extraction is correct even if line_total ≠ quantity × unit_price
       * This is NOT an error - it is the expected behavior for package discounts
     ```
   - `priority`: `10`
   - `is_active`: `true`

3. **Validation Rule Snippet**：
   - `snippet_type`: `'validation_rule'`
   - `content`: 
     ```
     Package Price Discount Validation:
     - If raw_text contains patterns like "2/$", "3 for $", "Buy X Get Y":
       * Check if multiple items with same/similar product_name exist
       * Verify their line_totals sum to the package price (e.g., $9.00 for "2/$9.00")
       * If sum matches package price, this is CORRECT - do not flag as inconsistent_price
       * Only flag as error if line_totals do NOT sum to the stated package price
     ```
   - `priority`: `10`
   - `is_active`: `true`

**Matching Rules**：
- `match_type`: `'regex'`, `match_pattern`: `'\d+/\$'`, `priority`: `100` (匹配 "2/$9.00")
- `match_type`: `'regex'`, `match_pattern`: `'\d+\s+for\s+\$'`, `priority`: `100` (匹配 "2 for $9.00")
- `match_type`: `'regex'`, `match_pattern`: `'\d+\s+for\s+\d+'`, `priority`: `90` (匹配 "2 for 9")
- `match_type`: `'regex'`, `match_pattern`: `'\d+\s*/\s*\$\d+'`, `priority`: `100` (匹配 "2 /$9" 带空格)
- `match_type`: `'keyword'`, `match_pattern`: `'discount'`, `priority`: `85`
- `match_type`: `'keyword'`, `match_pattern`: `'buy'`, `priority`: `80`
- `match_type`: `'keyword'`, `match_pattern`: `'package price'`, `priority`: `80`
- `match_type`: `'keyword'`, `match_pattern`: `'bulk discount'`, `priority`: `80`
- `match_type`: `'keyword'`, `match_pattern`: `'sale'`, `priority`: `75`

---

### 2.3 Deposit and Fee Tag

**Tag 定义**：
- `tag_name`: `'deposit_and_fee'`
- `tag_type`: `'general'`
- `description`: `'Bottle deposits, environment fees, and similar charges (not tax)'`
- `priority`: `70`
- `is_active`: `true`

**Snippets**：

1. **System Message Snippet**：
   - `snippet_type`: `'system_message'`
   - `content`: 
     ```
     You are a receipt parsing expert. When you encounter bottle deposits, environment fees, or similar charges:
     1. These are legitimate line items and should be included in the items array
     2. These are NOT tax - do not include them in the tax field
     3. These charges are part of the total and should be included in sum calculations
     4. Common examples: "Bottle deposit", "Env fee", "Environmental fee", "CRF", "Container fee", "Bag fee"
     ```
   - `priority`: `10`
   - `is_active`: `true`

2. **Prompt Addition Snippet**：
   - `snippet_type`: `'prompt_addition'`
   - `content`: 
     ```
     ## Deposits and Fees (NOT Tax):
     
     When you see items like:
     - "Bottle deposit" or "Bottle Deposit" (e.g., "Bottle deposit $0.10")
     - "Env fee" or "Environment fee" or "Environmental fee" (e.g., "Env fee (CRF) $0.01")
     - "CRF" (Container Recycling Fee)
     - "Container fee", "Bag fee", or similar charges
     
     **IMPORTANT RULES:**
     1. **These are legitimate line items** - include them in the items array with:
        - product_name: the exact name from receipt (e.g., "Bottle deposit", "Env fee (CRF)")
        - line_total: the amount shown (e.g., 0.10, 0.01)
        - quantity: usually 1
        - category: can be null or a descriptive category like "FEE" or "DEPOSIT"
        - is_on_sale: false
     
     2. **These are NOT tax** - do NOT include them in the tax field
        - If tax is explicitly stated separately, use that value
        - If tax is not stated, set tax to null (NOT the sum of deposits/fees)
     
     3. **These are part of the total** - they should be included when calculating:
        - Sum of all line_totals should include deposits/fees
        - Total = sum(line_totals) + tax (if tax exists)
     
     4. **Common patterns to identify:**
        - "Bottle deposit" followed by an amount
        - "Env fee", "Environmental fee", "CRF" followed by an amount
        - Usually small amounts (e.g., $0.10, $0.01, $0.05)
        - Often appear near the end of the receipt before total
     
     5. **Example:**
        - Receipt shows: "Bottle deposit $0.10" and "Env fee (CRF) $0.01"
        - Include both as separate items in items array
        - If total = $54.10 and sum of product line_totals = $54.00, then:
          * tax should be null (if not explicitly stated)
          * OR tax should be the explicitly stated tax amount
          * The $0.11 difference is deposits/fees, NOT tax
     ```
   - `priority`: `10`
   - `is_active`: `true`

**Matching Rules**：
- `match_type`: `'keyword'`, `match_pattern`: `'bottle deposit'`, `priority`: `100`
- `match_type`: `'keyword'`, `match_pattern`: `'bottle'`, `priority`: `95`
- `match_type`: `'keyword'`, `match_pattern`: `'env fee'`, `priority`: `100`
- `match_type`: `'keyword'`, `match_pattern`: `'environmental fee'`, `priority`: `100`
- `match_type`: `'keyword'`, `match_pattern`: `'environment fee'`, `priority`: `100`
- `match_type`: `'keyword'`, `match_pattern`: `'environment'`, `priority`: `95`
- `match_type`: `'keyword'`, `match_pattern`: `'crf'`, `priority`: `100`
- `match_type`: `'keyword'`, `match_pattern`: `'container fee'`, `priority`: `90`
- `match_type`: `'keyword'`, `match_pattern`: `'bag fee'`, `priority`: `90`
- `match_type`: `'keyword'`, `match_pattern`: `'deposit'`, `priority`: `85`
- `match_type`: `'regex'`, `match_pattern`: `'bottle\s+deposit'`, `priority`: `100`
- `match_type`: `'regex'`, `match_pattern`: `'env\s+fee'`, `priority`: `100`
- `match_type`: `'regex'`, `match_pattern`: `'environment\s+fee'`, `priority`: `100`
- `match_type`: `'regex'`, `match_pattern`: `'environmental\s+fee'`, `priority`: `100`

**Location-based Matching Rules** (通过 API 或脚本添加)：
- `match_type`: `'location_state'`, `match_pattern`: `'BC'`, `priority`: `80` (British Columbia, Canada)
- `match_type`: `'location_state'`, `match_pattern`: `'HI'`, `priority`: `80` (Hawaii, USA)
- `match_type`: `'location_state'`, `match_pattern`: `'CA'`, `priority`: `80` (California, USA)
- `match_type`: `'location_country'`, `match_pattern`: `'CA'`, `priority`: `80` (Canada)

---

### 2.4 Membership Card Tag

**Tag 定义**：
- `tag_name`: `'membership_card'`
- `tag_type`: `'general'`
- `description`: `'Membership card number extraction and handling'`
- `priority`: `50`
- `is_active`: `true`

**Snippets**：

1. **Prompt Addition Snippet**：
   - `snippet_type`: `'prompt_addition'`
   - `content`: 
     ```
     ## Membership Card Handling:
     - If you see membership card numbers (e.g., "***600032371", "会员卡 1234567890123"), extract to "membership_number" field in receipt object
     - Ignore lines with membership card numbers that have $0.00 line_total (these are not products)
     ```
   - `priority`: `10`
   - `is_active`: `true`

**Matching Rules**：
- `match_type`: `'regex'`, `match_pattern`: `'会员卡'`, `priority`: `100`
- `match_type`: `'regex'`, `match_pattern`: `'membership'`, `priority`: `90`
- `match_type`: `'regex'`, `match_pattern`: `'\*{3,}\d+'`, `priority`: `90` (匹配 "***600032371")

---

## 三、数据清理操作 (005_delete_old_receipts_without_hash.sql)

### 3.1 删除没有 file_hash 的旧 receipts

**操作描述**：
删除所有 `file_hash IS NULL` 的 receipts 记录及其相关数据。

**删除顺序**：
1. 先删除 `api_calls` 表中相关的记录（没有 CASCADE，需要手动删除）
2. 再删除 `store_candidates` 表中相关的记录（没有 CASCADE，需要手动删除）
3. 最后删除 `receipts` 表中的记录（会自动 CASCADE 删除 `receipt_processing_runs` 记录）

**SQL 模板**：
```sql
-- Step 1: 预览要删除的记录数
SELECT COUNT(*) FROM receipts WHERE file_hash IS NULL;
SELECT COUNT(*) FROM api_calls WHERE receipt_id IN (SELECT id FROM receipts WHERE file_hash IS NULL);
SELECT COUNT(*) FROM store_candidates WHERE receipt_id IN (SELECT id FROM receipts WHERE file_hash IS NULL);

-- Step 2: 删除 api_calls
DELETE FROM api_calls 
WHERE receipt_id IN (SELECT id FROM receipts WHERE file_hash IS NULL);

-- Step 3: 删除 store_candidates
DELETE FROM store_candidates 
WHERE receipt_id IN (SELECT id FROM receipts WHERE file_hash IS NULL);

-- Step 4: 删除 receipts (会自动 CASCADE 删除 receipt_processing_runs)
DELETE FROM receipts 
WHERE file_hash IS NULL;
```

**注意**：
- 这是一个不可逆操作，执行前务必预览记录数
- 建议先备份数据库
- 在生产环境执行前，先在测试环境验证

---

## 四、数据迁移操作 (008_update_current_stage.sql 中的数据迁移部分)

### 4.1 current_stage 值迁移

**操作描述**：
将 `receipts` 表中的 `current_stage` 值从旧值迁移到新值。

**映射关系**：
- `'manual'` → `'manual_review'`
- `'ocr'` → `'ocr_google'`
- `'pending'` → `'ocr_google'`
- `NULL` → 根据 `current_status` 决定：
  - 如果 `current_status = 'success'` → `'success'`
  - 如果 `current_status = 'failed'` → `'failed'`
  - 如果 `current_status = 'needs_review'` → `'manual_review'`
  - 其他情况 → `'ocr_google'`

**SQL 模板**：
```sql
-- 更新 'manual' 到 'manual_review'
UPDATE receipts SET current_stage = 'manual_review' WHERE current_stage = 'manual';

-- 更新 'ocr' 到 'ocr_google'
UPDATE receipts SET current_stage = 'ocr_google' WHERE current_stage = 'ocr';

-- 更新 'pending' 到 'ocr_google'
UPDATE receipts SET current_stage = 'ocr_google' WHERE current_stage = 'pending';

-- 更新 NULL 值（根据 current_status）
UPDATE receipts 
SET current_stage = CASE
  WHEN current_status = 'success' THEN 'success'
  WHEN current_status = 'failed' THEN 'failed'
  WHEN current_status = 'needs_review' THEN 'manual_review'
  ELSE 'ocr_google'
END
WHERE current_stage IS NULL;
```

**注意**：
- 这个操作是幂等的，可以安全地多次执行
- 执行前会先删除旧的 CHECK 约束，执行后添加新的 CHECK 约束

---

## 五、数据回填操作 (006_add_validation_status.sql 中的数据回填部分)

### 5.1 validation_status 字段回填

**操作描述**：
从现有的 `receipt_processing_runs.output_payload._metadata.validation_status` 中提取值，回填到新添加的 `validation_status` 字段。

**SQL 模板**：
```sql
UPDATE receipt_processing_runs
SET validation_status = (
  CASE 
    WHEN output_payload->'_metadata'->>'validation_status' IS NOT NULL 
    THEN output_payload->'_metadata'->>'validation_status'
    ELSE 'unknown'
  END
)
WHERE stage = 'llm' 
  AND output_payload IS NOT NULL
  AND validation_status IS NULL;
```

**注意**：
- 只更新 `stage = 'llm'` 的记录
- 只更新 `validation_status IS NULL` 的记录（避免覆盖已有值）
- 如果 `output_payload._metadata.validation_status` 不存在，设置为 `'unknown'`

---

## 六、数据回填操作 (007_add_chain_name_to_store_locations.sql 中的数据回填部分)

### 6.1 chain_name 字段回填

**操作描述**：
从 `store_chains` 表中获取 `name`，回填到 `store_locations.chain_name` 字段。

**SQL 模板**：
```sql
UPDATE store_locations sl
SET chain_name = sc.name
FROM store_chains sc
WHERE sl.chain_id = sc.id
  AND (sl.chain_name IS NULL OR sl.chain_name != sc.name);
```

**注意**：
- 只更新 `chain_name IS NULL` 或与 `store_chains.name` 不一致的记录
- 这个操作是幂等的，可以安全地多次执行
- 未来通过触发器自动保持同步

---

## 七、增强的 Deposit and Fee 匹配规则 (010_enhance_deposit_fee_rag.sql)

### 7.1 额外的匹配规则

**操作描述**：
为 `deposit_and_fee` tag 添加额外的匹配规则，提高检测准确性。

**Tag 创建**（如果不存在）：
- `tag_name`: `'deposit_and_fee'`
- `tag_type`: `'general'`
- `description`: `'Bottle deposits, environment fees, and similar charges (not tax)'`
- `priority`: `70`
- `is_active`: `true`

**额外的 Matching Rules**：
- `match_type`: `'keyword'`, `match_pattern`: `'bottle'`, `priority`: `95`
- `match_type`: `'keyword'`, `match_pattern`: `'environment'`, `priority`: `95`
- `match_type`: `'keyword'`, `match_pattern`: `'environmental'`, `priority`: `95`
- `match_type`: `'regex'`, `match_pattern`: `'environment\s+fee'`, `priority`: `100`
- `match_type`: `'regex'`, `match_pattern`: `'environmental\s+fee'`, `priority`: `100`
- `match_type`: `'regex'`, `match_pattern`: `'bottle\s+deposit'`, `priority`: `100`

**SQL 模板**：
```sql
-- 获取或创建 tag
DO $$
DECLARE
  deposit_fee_tag_id UUID;
BEGIN
  SELECT id INTO deposit_fee_tag_id FROM prompt_tags WHERE tag_name = 'deposit_and_fee';
  
  IF deposit_fee_tag_id IS NULL THEN
    INSERT INTO prompt_tags (tag_name, tag_type, description, priority, is_active)
    VALUES (
      'deposit_and_fee',
      'general',
      'Bottle deposits, environment fees, and similar charges (not tax)',
      70,
      TRUE
    )
    ON CONFLICT (tag_name) DO UPDATE SET
      description = EXCLUDED.description,
      priority = EXCLUDED.priority,
      updated_at = NOW()
    RETURNING id INTO deposit_fee_tag_id;
  END IF;
  
  -- 插入额外的匹配规则
  INSERT INTO tag_matching_rules (tag_id, match_type, match_pattern, priority, is_active)
  VALUES
    (deposit_fee_tag_id, 'keyword', 'bottle', 95, TRUE),
    (deposit_fee_tag_id, 'keyword', 'environment', 95, TRUE),
    (deposit_fee_tag_id, 'keyword', 'environmental', 95, TRUE),
    (deposit_fee_tag_id, 'regex', 'environment\s+fee', 100, TRUE),
    (deposit_fee_tag_id, 'regex', 'environmental\s+fee', 100, TRUE),
    (deposit_fee_tag_id, 'regex', 'bottle\s+deposit', 100, TRUE)
  ON CONFLICT DO NOTHING;
END $$;
```

**注意**：
- 使用 `ON CONFLICT DO NOTHING` 避免重复插入
- 这些规则是对 009 中已有规则的补充

---

## 八、初始化方法

### 8.1 使用 RAG 管理 API

所有 RAG 相关的数据插入应通过以下 API 完成：
- `POST /api/rag/tags` - 创建 tag
- `POST /api/rag/tags/{tag_name}/snippets` - 创建 snippet
- `POST /api/rag/tags/{tag_name}/matching-rules` - 创建匹配规则

**示例**：使用 `backend/scripts/init_deposit_fee_rag.py` 脚本初始化 `deposit_and_fee` tag。

### 8.2 使用初始化脚本

运行以下脚本可以自动初始化所有 RAG 数据：
```bash
python backend/scripts/init_deposit_fee_rag.py
```

### 8.3 直接 SQL 插入（不推荐）

只有在无法使用 API 或脚本的情况下，才使用本文档中的 SQL 模板直接插入数据。

---

## 九、验证查询

### 9.1 验证 Tags
```sql
SELECT * FROM prompt_tags ORDER BY priority DESC;
```

### 9.2 验证 Snippets
```sql
SELECT ps.*, pt.tag_name 
FROM prompt_snippets ps 
JOIN prompt_tags pt ON ps.tag_id = pt.id 
ORDER BY pt.priority DESC, ps.priority DESC;
```

### 9.3 验证 Matching Rules
```sql
SELECT tmr.*, pt.tag_name 
FROM tag_matching_rules tmr 
JOIN prompt_tags pt ON tmr.tag_id = pt.id 
ORDER BY pt.priority DESC, tmr.priority DESC;
```

### 9.4 验证 Store Chains
```sql
SELECT * FROM store_chains ORDER BY name;
```

---

*文档创建时间：2026-01-31*
*最后更新：2026-01-31*
