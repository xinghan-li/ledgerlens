# Tag Matching Rules 说明文档

本文档详细解释了 `tag_matching_rules` 表中所有 `match_type` 和 `match_pattern` 的含义和用法。

## 概述

`tag_matching_rules` 表用于定义如何从 OCR 文本、商店名称或位置信息中检测并应用 RAG tags。每个规则包含：
- `match_type`: 匹配类型（如何匹配）
- `match_pattern`: 匹配模式（匹配什么）
- `priority`: 优先级（数字越大优先级越高）
- `is_active`: 是否激活

---

## Match Types 详解

### 1. `store_name` - 精确商店名称匹配

**说明**: 在 `merchant_name` 中精确查找 `match_pattern`（不区分大小写，子字符串匹配）

**匹配逻辑**: 
```python
if merchant_name and match_pattern.lower() in merchant_name.lower():
    matched = True
```

**示例**:
| match_type | match_pattern | Example merchant_name | 是否匹配 | 说明 |
|------------|---------------|----------------------|---------|------|
| store_name | "costco" | "Costco Warehouse" | ✅ | "costco" 在 "Costco Warehouse" 中 |
| store_name | "walmart" | "Walmart Supercenter" | ✅ | 子字符串匹配 |
| store_name | "target" | "Target Store #1234" | ✅ | 不区分大小写 |

**使用场景**: 当你知道确切的商店名称时使用

---

### 2. `fuzzy_store_name` - 模糊商店名称匹配

**说明**: 使用字符串相似度算法（rapidfuzz）匹配商店名称，相似度 >= 80% 时匹配

**匹配逻辑**: 
```python
similarity = fuzz.ratio(merchant_name.lower(), match_pattern.lower())
if similarity >= 80:  # 80% 相似度阈值
    matched = True
```

**示例**:
| match_type | match_pattern | Example merchant_name | 相似度 | 是否匹配 | 说明 |
|------------|---------------|----------------------|-------|---------|------|
| fuzzy_store_name | "t&t" | "T&T Supermarket" | ~90% | ✅ | 相似度高 |
| fuzzy_store_name | "tnt" | "TNT Supermarket" | ~90% | ✅ | OCR 可能识别错误 |
| fuzzy_store_name | "t & t" | "T&T Supermarket" | ~85% | ✅ | 空格不影响 |
| fuzzy_store_name | "costco" | "Costco" | 100% | ✅ | 完全匹配 |
| fuzzy_store_name | "walmart" | "Target" | ~40% | ❌ | 相似度太低 |

**使用场景**: 
- OCR 识别可能有拼写错误
- 商店名称有多种写法（如 "T&T" vs "TNT"）
- 需要容错匹配

---

### 3. `keyword` - 关键词匹配

**说明**: 在 `raw_text` 或 `merchant_name` 中查找关键词（不区分大小写，子字符串匹配）

**匹配逻辑**: 
```python
pattern_lower = match_pattern.lower()
if pattern_lower in raw_text.lower() or (merchant_name and pattern_lower in merchant_name.lower()):
    matched = True
```

**示例**:
| match_type | match_pattern | Example raw_text | 是否匹配 | 说明 |
|------------|---------------|------------------|---------|------|
| keyword | "bottle deposit" | "Bottle deposit $0.10" | ✅ | 在 OCR 文本中找到 |
| keyword | "env fee" | "Env fee (CRF) $0.01" | ✅ | 不区分大小写 |
| keyword | "crf" | "Container Recycling Fee (CRF)" | ✅ | 子字符串匹配 |
| keyword | "discount" | "Special discount today!" | ✅ | 关键词匹配 |
| keyword | "bottle" | "Bottle Deposit" | ✅ | 部分匹配 |

**使用场景**: 
- 在 receipt 文本中查找特定关键词
- 匹配费用类型（如 "bottle deposit", "env fee"）
- 匹配折扣标识（如 "discount", "sale"）

**注意**: `keyword` 和 `ocr_pattern` 功能类似，但 `keyword` 更通用，可以匹配任何文本

---

### 4. `regex` - 正则表达式匹配

**说明**: 使用正则表达式在 `raw_text` 或 `merchant_name` 中搜索（不区分大小写）

**匹配逻辑**: 
```python
pattern = re.compile(match_pattern, re.IGNORECASE)
if pattern.search(raw_text) or (merchant_name and pattern.search(merchant_name)):
    matched = True
```

**示例**:
| match_type | match_pattern | Example raw_text | 是否匹配 | 说明 |
|------------|---------------|------------------|---------|------|
| regex | `\d+/\$` | "2/$9.00" | ✅ | 匹配 "数字/$" 模式 |
| regex | `\d+\s+for\s+\$` | "2 for $9.00" | ✅ | 匹配 "数字 for $" 模式 |
| regex | `bottle\s+deposit` | "Bottle deposit $0.10" | ✅ | 匹配 "bottle" + 空格 + "deposit" |
| regex | `env\s+fee` | "Env fee $0.01" | ✅ | 匹配 "env" + 空格 + "fee" |
| regex | `会员卡` | "会员卡 1234567890123" | ✅ | 匹配中文字符 |
| regex | `\d+/\$\d+` | "2/$9" | ✅ | 匹配 "数字/$数字" |

**常用正则表达式模式**:
- `\d+`: 一个或多个数字
- `\s+`: 一个或多个空格
- `\$`: 转义的美元符号
- `[a-zA-Z]+`: 一个或多个字母

**使用场景**: 
- 匹配复杂模式（如 "2/$9.00", "3 for $10"）
- 匹配特定格式（如 "会员卡" + 数字）
- 需要精确控制匹配规则时

**注意**: 在 SQL 中存储时，反斜杠需要转义（如 `\\d+`），但在 Python 中使用时是 `\d+`

---

### 5. `ocr_pattern` - OCR 文本模式匹配

**说明**: 在 `raw_text` 中查找简单模式（不区分大小写，子字符串匹配）

**匹配逻辑**: 
```python
if match_pattern.lower() in raw_text.lower():
    matched = True
```

**示例**:
| match_type | match_pattern | Example raw_text | 是否匹配 | 说明 |
|------------|---------------|------------------|---------|------|
| ocr_pattern | "2/$" | "2/$9.00" | ✅ | 在 OCR 文本中找到 |
| ocr_pattern | "会员卡" | "会员卡 1234567890123" | ✅ | 中文字符匹配 |
| ocr_pattern | "FP" | "FP $4.99" | ✅ | 匹配 "FP" 前缀 |

**使用场景**: 
- 匹配简单的 OCR 文本模式
- 与 `keyword` 类似，但专门用于 OCR 文本
- 通常用于匹配特定的 receipt 格式标识符

**注意**: `ocr_pattern` 和 `keyword` 功能几乎相同，区别在于 `keyword` 也会检查 `merchant_name`

---

### 6. `location_state` - 州/省匹配

**说明**: 根据 receipt 的 state/province 代码匹配（需要传入 `state` 或 `location_id` 参数）

**匹配逻辑**: 
```python
if rule.get("match_type") == "location_state" and state:
    match_pattern = rule.get("match_pattern", "").upper()
    state_normalized = state.upper()
    if match_pattern == state_normalized or match_pattern in state_normalized:
        matched = True
```

**示例**:
| match_type | match_pattern | Receipt state | 是否匹配 | 说明 |
|------------|---------------|---------------|---------|------|
| location_state | "BC" | "BC" | ✅ | 精确匹配 |
| location_state | "BC" | "British Columbia" | ❌ | 只匹配代码，不匹配全名 |
| location_state | "HI" | "HI" | ✅ | 夏威夷州 |
| location_state | "CA" | "CA" | ✅ | 加利福尼亚州 |
| location_state | "CA" | "Canada" | ❌ | "CA" 是州代码，不是国家代码 |

**使用场景**: 
- 根据 receipt 的州/省应用特定的 RAG（如 BC 有 bottle deposit）
- 需要州/省特定的处理规则时

**注意**: 
- `match_pattern` 应该是标准的州/省代码（如 "BC", "HI", "CA"）
- 需要从 `store_locations` 表或 receipt 地址中提取 state
- 目前不在数据库 CHECK 约束中，但在代码中实现

---

### 7. `location_country` - 国家匹配

**说明**: 根据 receipt 的 country 代码匹配（需要传入 `country_code` 或 `location_id` 参数）

**匹配逻辑**: 
```python
if rule.get("match_type") == "location_country" and country_code:
    match_pattern = rule.get("match_pattern", "").upper()
    country_normalized = country_code.upper()
    if match_pattern == country_normalized or match_pattern in country_normalized:
        matched = True
```

**示例**:
| match_type | match_pattern | Receipt country_code | 是否匹配 | 说明 |
|------------|---------------|---------------------|---------|------|
| location_country | "CA" | "CA" | ✅ | 加拿大 |
| location_country | "US" | "US" | ✅ | 美国 |
| location_country | "CA" | "Canada" | ❌ | 只匹配代码，不匹配全名 |

**使用场景**: 
- 根据 receipt 的国家应用特定的 RAG
- 需要国家特定的处理规则时（如加拿大的 bottle deposit 规则）

**注意**: 
- `match_pattern` 应该是标准的国家代码（如 "CA", "US"）
- 需要从 `store_locations` 表或 receipt 地址中提取 country_code
- 目前不在数据库 CHECK 约束中，但在代码中实现

---

## 实际使用示例

### 示例 1: T&T Supermarket Tag

```sql
-- 使用 fuzzy_store_name 匹配商店名称（容错 OCR 错误）
INSERT INTO tag_matching_rules (tag_id, match_type, match_pattern, priority)
VALUES 
  (tt_tag_id, 'fuzzy_store_name', 't&t', 100),
  (tt_tag_id, 'fuzzy_store_name', 'tnt', 100),  -- OCR 可能识别为 "TNT"
  (tt_tag_id, 'keyword', 't&t supermarket', 90);
```

### 示例 2: Package Price Discount Tag

```sql
-- 使用 regex 匹配折扣模式
INSERT INTO tag_matching_rules (tag_id, match_type, match_pattern, priority)
VALUES 
  (discount_tag_id, 'regex', '\d+/\$', 100),           -- "2/$9.00"
  (discount_tag_id, 'regex', '\d+\s+for\s+\$', 100),   -- "2 for $9.00"
  (discount_tag_id, 'keyword', 'discount', 85),
  (discount_tag_id, 'keyword', 'sale', 75);
```

### 示例 3: Deposit and Fee Tag

```sql
-- 使用 keyword 和 regex 匹配费用类型
INSERT INTO tag_matching_rules (tag_id, match_type, match_pattern, priority)
VALUES 
  (deposit_fee_tag_id, 'keyword', 'bottle deposit', 100),
  (deposit_fee_tag_id, 'keyword', 'env fee', 100),
  (deposit_fee_tag_id, 'regex', 'bottle\s+deposit', 100),  -- 匹配空格
  (deposit_fee_tag_id, 'location_state', 'BC', 80),       -- BC 省有 bottle deposit
  (deposit_fee_tag_id, 'location_country', 'CA', 80);     -- 加拿大有 bottle deposit
```

### 示例 4: Membership Card Tag

```sql
-- 使用 regex 匹配中文和英文
INSERT INTO tag_matching_rules (tag_id, match_type, match_pattern, priority)
VALUES 
  (membership_tag_id, 'regex', '会员卡', 100),      -- 中文
  (membership_tag_id, 'keyword', 'membership', 90); -- 英文
```

---

## 优先级说明

- **优先级数字越大，优先级越高**
- 当多个规则匹配时，tag 的最终优先级由匹配规则的最高 priority 决定
- 建议优先级范围：
  - `100`: 高优先级（精确匹配，如 "bottle deposit"）
  - `90-95`: 中高优先级（常见模式）
  - `80-85`: 中优先级（一般模式）
  - `70-75`: 低优先级（可能误匹配的模式）

---

## 匹配流程

1. **检测阶段**: 遍历所有 `tag_matching_rules`，根据 `match_type` 和 `match_pattern` 检测匹配的 tags
2. **优先级排序**: 按匹配规则的 `priority` 对检测到的 tags 排序
3. **加载 RAG**: 为匹配的 tags 加载对应的 `prompt_snippets`
4. **组合 Prompt**: 将 RAG snippets 组合到最终的 system_message 和 user_message 中

---

## 注意事项

1. **数据库约束**: `location_state` 和 `location_country` 目前不在数据库 CHECK 约束中，但在代码中实现
2. **转义字符**: 在 SQL 中存储 regex 时，反斜杠需要转义（`\\d+`），但在 Python 中使用时是 `\d+`
3. **大小写**: 所有匹配都是不区分大小写的（除了 location 匹配，会转换为大写比较）
4. **性能**: `fuzzy_store_name` 使用字符串相似度算法，可能比其他匹配类型稍慢
5. **重复匹配**: 同一个 tag 可能被多个规则匹配，系统会自动去重

---

## 总结

| match_type | 用途 | 匹配对象 | 精确度 | 性能 |
|------------|------|---------|--------|------|
| `store_name` | 精确商店名称 | merchant_name | 高 | 快 |
| `fuzzy_store_name` | 模糊商店名称 | merchant_name | 中 | 中 |
| `keyword` | 关键词 | raw_text, merchant_name | 中 | 快 |
| `regex` | 正则表达式 | raw_text, merchant_name | 高 | 中 |
| `ocr_pattern` | OCR 模式 | raw_text | 中 | 快 |
| `location_state` | 州/省 | state (从 location_id 提取) | 高 | 快 |
| `location_country` | 国家 | country_code (从 location_id 提取) | 高 | 快 |

选择合适的 `match_type` 可以平衡匹配准确性和性能。
