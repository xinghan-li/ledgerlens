# Categorization Rules Data

## 文件说明

### `initial_categorization_rules.csv`

初始的商品分类规则数据，包含：

1. **Universal Rules（通用规则）**：适用于所有商店的商品分类
2. **Store-Specific Rules（商店专属规则）**：特定商店链的商品分类覆盖规则

## 匹配逻辑

系统会按以下优先级查找匹配规则：

```
1. Store-Specific Exact Match（商店专属精确匹配）
   ↓ 没找到
2. Universal Exact Match（通用精确匹配）
   ↓ 没找到
3. Store-Specific Fuzzy Match（商店专属模糊匹配）
   ↓ 没找到
4. Universal Fuzzy Match（通用模糊匹配）
   ↓ 没找到
5. Store-Specific Contains Match（商店专属包含匹配）
   ↓ 没找到
6. Universal Contains Match（通用包含匹配）
```

### 实际例子

**场景 1: 用户在 Costco 买了 "NAAN BREAD"**

```
1. 标准化名称: "NAAN BREAD" → "naan"
2. 查找 Costco 的 store_chain_id
3. 匹配规则:
   - 查找: normalized_name="naan" + store_chain_id=Costco
   - 找到: Grocery/Bakery (priority=50)
4. 结果: 分类为 Bakery（商店专属规则）
```

**场景 2: 用户在 Safeway 买了 "naan"（CSV中没有Safeway规则）**

```
1. 标准化名称: "naan"
2. 查找 Safeway 的 store_chain_id
3. 匹配规则:
   - 查找: normalized_name="naan" + store_chain_id=Safeway
   - 没找到商店专属规则
   - 回退到通用规则: normalized_name="naan" + store_chain_id=NULL
   - 找到: Grocery/Deli (priority=250)
4. 结果: 分类为 Deli（通用规则）
```

**场景 3: 用户在 Walmart 买了 "naan flatbread"**

```
1. 标准化名称: "naan flatbread"
2. 精确匹配: 没找到
3. 模糊匹配:
   - similarity("naan flatbread", "naan") = 0.95 > 0.90 threshold
   - 查找 Walmart 的规则: normalized_name="naan" + store_chain_id=Walmart
   - 找到: Grocery/Deli (priority=50)
4. 结果: 分类为 Deli（模糊匹配 + 商店专属规则）
```

**场景 4: 新的沃尔玛门店（数据库中没有这个 store_location）**

```
1. 用户在 "Walmart #4521" 买了 "naan"
2. 查找 store_location: 没找到这个具体门店
3. 查找 store_chain: 找到 "Walmart" 
4. 使用 Walmart 的 chain-level 规则
5. 结果: 分类为 Deli（使用 chain 规则）
```

## Priority 优先级说明

```
1-100:   Store-specific rules（商店专属规则，最高优先级）
101-199: Category-specific overrides（分类专属覆盖）
200-299: Universal rules（通用规则）
300+:    Low priority fallbacks（低优先级兜底规则）
```

**Priority 规则：**
- 数字**越小**，优先级**越高**
- 同优先级的规则按 `times_matched` 排序（使用次数越多越优先）

## CSV 格式说明

```csv
normalized_name,store_chain_name,category_path,match_type,priority,source,notes
banana,NULL,Grocery/Produce/Fruit,fuzzy,200,seed,Universal: bananas are always fruit
naan,Walmart,Grocery/Deli,fuzzy,50,seed,Walmart keeps naan in deli section
```

| 字段 | 说明 | 示例 |
|------|------|------|
| `normalized_name` | 标准化商品名（小写，无标点） | `banana`, `naan`, `ice cream` |
| `store_chain_name` | 商店链名称（NULL=通用规则） | `Walmart`, `Costco Wholesale`, `NULL` |
| `category_path` | 完整分类路径 | `Grocery/Produce/Fruit` |
| `match_type` | 匹配类型 | `exact`, `fuzzy`, `contains` |
| `priority` | 优先级（1-1000） | `50`, `200`, `300` |
| `source` | 规则来源 | `seed`, `manual`, `auto` |
| `notes` | 说明（可选） | `Universal: bananas are always fruit` |

### Match Type 说明

- **exact**: 精确匹配（`normalized_name = input`）
- **fuzzy**: 模糊匹配（使用 PostgreSQL `similarity()` 函数）
- **contains**: 包含匹配（`input LIKE '%normalized_name%'`）

## 导入数据

### 1. 前提条件

确保已运行以下 migrations：

```bash
# 在 Supabase SQL Editor 中依次运行：
015_add_categories_tree.sql
016_add_products_catalog.sql
019_add_categorization_rules.sql
```

### 2. 运行导入脚本

```bash
cd backend
python scripts/import_categorization_rules.py
```

### 3. 验证导入

```sql
-- 查看已导入的规则数量
SELECT COUNT(*) FROM product_categorization_rules;

-- 查看通用规则
SELECT * FROM product_categorization_rules 
WHERE store_chain_id IS NULL 
ORDER BY priority, normalized_name;

-- 查看商店专属规则
SELECT 
  r.normalized_name,
  sc.name as store,
  c.path as category,
  r.priority
FROM product_categorization_rules r
JOIN store_chains sc ON r.store_chain_id = sc.id
JOIN categories c ON r.category_id = c.id
ORDER BY r.priority, sc.name, r.normalized_name;
```

### 4. 测试匹配

```sql
-- 测试通用规则: 香蕉
SELECT * FROM find_categorization_rule('banana', NULL);

-- 测试商店专属规则: Costco 的 naan
SELECT * FROM find_categorization_rule('naan', '<costco-chain-uuid>');

-- 测试模糊匹配: naan bread
SELECT * FROM find_categorization_rule('naan bread', NULL);
```

## 添加新规则

### 方式 1: 直接编辑 CSV

1. 编辑 `initial_categorization_rules.csv`
2. 添加新行
3. 重新运行导入脚本（会跳过重复规则）

### 方式 2: 通过数据库直接插入

```sql
-- 添加通用规则
INSERT INTO product_categorization_rules (
  normalized_name,
  store_chain_id,
  category_id,
  match_type,
  priority,
  source
) VALUES (
  'avocado',
  NULL,
  (SELECT id FROM categories WHERE path = 'Grocery/Produce/Fruit'),
  'fuzzy',
  200,
  'manual'
);

-- 添加商店专属规则
INSERT INTO product_categorization_rules (
  normalized_name,
  store_chain_id,
  category_id,
  match_type,
  priority,
  source
) VALUES (
  'rotisserie chicken',
  (SELECT id FROM store_chains WHERE name = 'Costco Wholesale'),
  (SELECT id FROM categories WHERE path = 'Grocery/Deli'),
  'exact',
  50,
  'manual'
);
```

### 方式 3: 通过用户纠正学习（未来实现）

当用户手动修改商品分类时，系统会自动：
1. 创建新的 `manual` 规则
2. 设置高优先级（priority < 100）
3. 下次遇到相似商品自动应用

## 维护规则

### 查看使用统计

```sql
-- 最常用的规则
SELECT 
  r.normalized_name,
  sc.name as store,
  c.path as category,
  r.times_matched,
  r.last_matched_at
FROM product_categorization_rules r
LEFT JOIN store_chains sc ON r.store_chain_id = sc.id
JOIN categories c ON r.category_id = c.id
ORDER BY r.times_matched DESC
LIMIT 20;
```

### 删除冲突规则

```sql
-- 找出相同商品的多个规则
SELECT 
  normalized_name,
  COUNT(*) as rule_count
FROM product_categorization_rules
WHERE store_chain_id IS NULL
GROUP BY normalized_name
HAVING COUNT(*) > 1;

-- 删除特定规则
DELETE FROM product_categorization_rules
WHERE normalized_name = 'xxx' 
  AND store_chain_id = 'yyy'
  AND category_id = 'zzz';
```

## 故障排查

### 问题: 规则不生效

1. **检查规则是否存在**:
   ```sql
   SELECT * FROM product_categorization_rules 
   WHERE normalized_name = 'your_product';
   ```

2. **检查优先级**:
   ```sql
   -- 查看所有相关规则的优先级
   SELECT * FROM product_categorization_rules 
   WHERE normalized_name LIKE '%your_product%'
   ORDER BY priority;
   ```

3. **测试匹配函数**:
   ```sql
   SELECT * FROM find_categorization_rule('your_product', NULL);
   SELECT * FROM find_categorization_rule('your_product', '<store-uuid>');
   ```

### 问题: 模糊匹配不准确

调整 `similarity_threshold`:

```sql
UPDATE product_categorization_rules
SET similarity_threshold = 0.95  -- 提高到 95%
WHERE normalized_name = 'problematic_product';
```

### 问题: 商店专属规则不生效

检查 `store_chain_id` 是否正确:

```sql
-- 查看所有商店链
SELECT id, name, normalized_name FROM store_chains;

-- 检查规则的 store_chain_id
SELECT 
  r.*,
  sc.name as store_name
FROM product_categorization_rules r
LEFT JOIN store_chains sc ON r.store_chain_id = sc.id
WHERE r.normalized_name = 'problematic_product';
```

## 性能优化

### 索引

已创建的索引（在 019 migration 中）:

```sql
CREATE INDEX rules_normalized_name_idx ON product_categorization_rules(normalized_name);
CREATE INDEX rules_name_store_idx ON product_categorization_rules(normalized_name, store_chain_id);
CREATE INDEX rules_normalized_name_trgm_idx ON product_categorization_rules USING gin(normalized_name gin_trgm_ops);
```

### 缓存策略

在应用层面可以实现：

1. **Memory Cache**: 缓存最常用的规则（前 1000 个）
2. **Store-specific Cache**: 按商店缓存规则
3. **LRU Cache**: 淘汰最少使用的规则

## 未来扩展

### 1. 机器学习增强

- 使用 ML 模型学习商品分类模式
- 自动生成新规则
- 优化 similarity_threshold

### 2. 用户自定义分类

- 允许用户创建自己的分类树
- 用户专属规则（`user_id` 字段）
- 用户之间共享规则

### 3. 条形码识别

- 添加 UPC/EAN 条形码支持
- 通过条形码精确匹配商品
- 自动填充商品信息

### 4. 多语言支持

- 支持多语言商品名称
- 商品名称翻译
- 跨语言模糊匹配
