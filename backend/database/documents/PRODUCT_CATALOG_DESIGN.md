# Product Catalog 设计文档

## 🎯 设计目标

将 LedgerLens 从"Excel 式账本"升级为"可扩展的产品级分析平台"，为未来的 PricePeek 打下基础。

---

## 📊 核心问题与解决方案

### 问题：无法跨小票聚合同一商品

**当前情况 (Migration 012):**
```sql
receipt_items (
  product_name TEXT,  -- "DOLE BANANA"
  brand TEXT,         -- "Dole"
  category_l1 TEXT,   -- "Grocery"
  category_l2 TEXT,   -- "Produce"
  category_l3 TEXT    -- "Fruit"
)
```

**问题示例：**
```
小票1: product_name = "DOLE BANANA"
小票2: product_name = "dole banana"
小票3: product_name = "Dole Bananas"
```

❌ **无法聚合**：系统认为这是3个不同商品

**解决方案 (Migration 016 + 017):**
```sql
products (
  id UUID,
  normalized_name TEXT,  -- "banana"
  brand_id UUID          -- → brands.id
)

receipt_items (
  product_id UUID  -- → products.id
)
```

✅ **可以聚合**：3条记录都指向同一个 product_id

---

## 🗂️ 新增表结构概览

### 1. `brands` (Migration 014)

**用途：** 品牌归一化

```sql
id              UUID
name            TEXT      -- "Dole"
normalized_name TEXT      -- "dole"
aliases         TEXT[]    -- ["DOLE", "Dole Food Company"]
usage_count     INT       -- 使用次数
```

**查询示例：**
```sql
-- 用户在 Dole 品牌上花了多少钱？
SELECT 
  b.name,
  COUNT(DISTINCT ri.receipt_id) as receipt_count,
  SUM(ri.line_total) as total_spent
FROM receipt_items ri
JOIN products p ON ri.product_id = p.id
JOIN brands b ON p.brand_id = b.id
WHERE ri.user_id = ?
  AND b.normalized_name = 'dole'
GROUP BY b.name;
```

---

### 2. `categories` (Migration 015)

**用途：** 树形分类结构（替代 category_l1/l2/l3）

```sql
id              UUID
parent_id       UUID      -- 父分类
level           INT       -- 层级 (1, 2, 3, 4)
name            TEXT      -- "Fruit"
normalized_name TEXT      -- "fruit"
path            TEXT      -- "Grocery/Produce/Fruit"
```

**示例数据：**
```
Level 1: Grocery
  Level 2: Produce
    Level 3: Fruit
    Level 3: Vegetables
  Level 2: Dairy
    Level 3: Milk
    Level 3: Cheese
```

**查询示例：**
```sql
-- 用户在 Produce 分类下花了多少？
SELECT 
  c.name as category,
  COUNT(ri.id) as item_count,
  SUM(ri.line_total) as total_spent
FROM receipt_items ri
JOIN products p ON ri.product_id = p.id
JOIN categories c ON p.category_id = c.id
WHERE ri.user_id = ?
  AND c.path LIKE 'Grocery/Produce%'  -- 包含所有 Produce 子分类
GROUP BY c.name;
```

---

### 3. `products` (Migration 016)

**用途：** 统一商品目录（核心表）

```sql
id              UUID
normalized_name TEXT      -- "banana"
brand_id        UUID      -- → brands.id
category_id     UUID      -- → categories.id
size            TEXT      -- "1 lb"
unit_type       TEXT      -- "lb"
variant_type    TEXT      -- "organic"
is_organic      BOOLEAN
aliases         TEXT[]    -- 搜索别名
usage_count     INT       -- 出现次数
```

**查询示例：**
```sql
-- 查找所有 banana 类产品
SELECT 
  p.normalized_name,
  b.name as brand,
  p.size,
  p.unit_type,
  p.usage_count
FROM products p
LEFT JOIN brands b ON p.brand_id = b.id
WHERE p.normalized_name LIKE '%banana%'
ORDER BY p.usage_count DESC;
```

---

### 4. `receipt_items.product_id` (Migration 017)

**用途：** 连接交易数据和商品目录

**新增列：**
```sql
ALTER TABLE receipt_items ADD COLUMN product_id UUID REFERENCES products(id);
ALTER TABLE receipt_items ADD COLUMN category_id UUID REFERENCES categories(id);
```

**查询示例：**
```sql
-- 用户购买某商品的历史记录
SELECT 
  p.normalized_name,
  b.name as brand,
  ri.unit_price,
  ri.quantity,
  rs.receipt_date,
  sl.name as store
FROM receipt_items ri
JOIN products p ON ri.product_id = p.id
LEFT JOIN brands b ON p.brand_id = b.id
JOIN receipts r ON ri.receipt_id = r.id
JOIN receipt_summaries rs ON r.id = rs.receipt_id
LEFT JOIN store_locations sl ON rs.store_location_id = sl.id
WHERE ri.user_id = ?
  AND p.normalized_name = 'banana'
ORDER BY rs.receipt_date DESC;
```

---

### 5. `price_snapshots` (Migration 018)

**用途：** PricePeek 价格聚合（从 receipt_items 派生）

```sql
id                    UUID
product_id            UUID      -- → products.id
store_location_id     UUID      -- → store_locations.id
snapshot_date         DATE
latest_price_cents    INT       -- 最新价格（分）
sample_count          INT       -- 样本数
avg_price_cents       INT       -- 平均价格
is_on_sale            BOOLEAN
confidence_score      NUMERIC   -- 置信度
```

**查询示例：**
```sql
-- Dole Banana 在各店的最新价格
SELECT 
  p.normalized_name,
  b.name as brand,
  sl.name as store,
  lp.latest_price_cents / 100.0 as price,
  lp.last_seen_date,
  lp.confidence_score
FROM latest_prices lp
JOIN products p ON lp.product_id = p.id
LEFT JOIN brands b ON p.brand_id = b.id
JOIN store_locations sl ON lp.store_location_id = sl.id
WHERE p.normalized_name = 'banana'
  AND b.normalized_name = 'dole'
ORDER BY lp.latest_price_cents;
```

---

## 🔄 数据流

### 1. 用户上传小票

```
Image Upload
    ↓
OCR (Google Document AI)
    ↓
LLM Processing (Gemini/GPT)
    ↓
{
  "items": [
    {
      "name": "DOLE BANANA",
      "brand": "Dole",
      "price": 0.79,
      "category": "Grocery > Produce > Fruit"
    }
  ]
}
```

### 2. 商品归一化 (New Logic)

```python
# 提取商品信息
raw_name = "DOLE BANANA"
brand_name = "Dole"
category_path = "Grocery/Produce/Fruit"

# 1. 查找或创建 brand
brand = find_or_create_brand("Dole")

# 2. 查找或创建 category
category = find_category_by_path("Grocery/Produce/Fruit")

# 3. 归一化商品名
normalized_name = normalize_product_name(raw_name)  # "banana"

# 4. 查找或创建 product
product = find_or_create_product(
    normalized_name="banana",
    brand_id=brand.id,
    category_id=category.id,
    unit_type="lb"
)

# 5. 保存 receipt_item
receipt_item = {
    "product_name": "DOLE BANANA",  # 保留原始名称
    "product_id": product.id,        # 链接到标准化商品
    "brand": "Dole",                 # 保留原始品牌
    "category_id": category.id,      # 链接到分类树
    "unit_price": 0.79,
    "line_total": 0.79
}
```

### 3. Dashboard 查询 (New Capability)

```sql
-- 用户在 Produce 分类下的花费
SELECT 
  c.name as category,
  SUM(ri.line_total) as total
FROM receipt_items ri
JOIN categories c ON ri.category_id = c.id
WHERE ri.user_id = ?
  AND c.path LIKE 'Grocery/Produce%'
GROUP BY c.name;

-- 用户购买最多的商品 Top 20
SELECT 
  p.normalized_name,
  b.name as brand,
  COUNT(*) as times_bought,
  SUM(ri.line_total) as total_spent,
  AVG(ri.unit_price) as avg_price
FROM receipt_items ri
JOIN products p ON ri.product_id = p.id
LEFT JOIN brands b ON p.brand_id = b.id
WHERE ri.user_id = ?
GROUP BY p.normalized_name, b.name
ORDER BY total_spent DESC
LIMIT 20;
```

### 4. PricePeek 查询 (Future)

```sql
-- 某商品在各店的价格对比
SELECT 
  p.normalized_name,
  b.name as brand,
  sl.name as store,
  sl.city,
  ps.latest_price_cents / 100.0 as price,
  ps.last_seen_date,
  ps.is_on_sale,
  ps.confidence_score
FROM price_snapshots ps
JOIN products p ON ps.product_id = p.id
LEFT JOIN brands b ON p.brand_id = b.id
JOIN store_locations sl ON ps.store_location_id = sl.id
WHERE p.normalized_name = 'banana'
  AND ps.snapshot_date = CURRENT_DATE
ORDER BY ps.latest_price_cents;
```

---

## ⚖️ 设计权衡

### 为什么保留 category_l1/l2/l3？

**保留原因：**
- ✅ 向后兼容现有数据
- ✅ 简化 LLM 输出格式
- ✅ 前端代码不需要立即修改
- ✅ 可以逐步迁移

**迁移策略：**
```
Phase 1: 保留 l1/l2/l3，同时填充 category_id
Phase 2: 前端/后端逐步切换到使用 category_id
Phase 3: 验证所有功能正常后，标记 l1/l2/l3 为 deprecated
Phase 4: 一年后完全移除 l1/l2/l3 列
```

### 为什么 product_id 初始为 nullable？

**原因：**
- 现有数据需要 backfill
- LLM 归一化逻辑需要时间开发
- 允许渐进式迁移

**未来：**
```sql
-- 所有数据 backfill 完成后
ALTER TABLE receipt_items 
ALTER COLUMN product_id SET NOT NULL;
```

---

## 🔮 未来扩展

### Phase 1: LedgerLens MVP (现在)
- ✅ Products catalog
- ✅ Category tree
- ✅ Brands table
- ✅ Cross-receipt product aggregation

### Phase 2: LedgerLens Pro (3个月)
- 📊 Dashboard with category breakdowns
- 📈 Price trend charts
- 🏷️ Brand loyalty analysis
- 📱 Mobile app

### Phase 3: PricePeek Launch (6个月)
- 🌍 Price snapshots
- 🔍 Cross-store price comparison
- 📢 Price alerts
- 👥 Community contributions

### Phase 4: Scale (1年+)
- 🤖 ML-based product matching
- 🏪 Store-specific promotions
- 📦 Subscription box optimization
- 🌐 Multi-country support

---

## 📚 文件清单

### Migration Files (按顺序运行)
1. ✅ `013_auto_create_user_on_signup.sql` - 用户自动创建
2. ✅ `014_add_brands_table.sql` - 品牌表
3. ✅ `015_add_categories_tree.sql` - 分类树
4. ✅ `016_add_products_catalog.sql` - 商品目录
5. ✅ `017_link_receipt_items_to_products.sql` - 连接交易和商品
6. ✅ `018_add_price_snapshots.sql` - 价格快照

### Documentation
- ✅ `MIGRATIONS_ORDER.md` - 执行顺序和依赖关系
- ✅ `PRODUCT_CATALOG_DESIGN.md` - 设计文档（本文件）
- 📖 `REFACTORING_SUMMARY.md` - 重构总结
- 📖 `2026-01-31_MIGRATION_NOTES.md` - 迁移笔记

---

## 🚀 Quick Start

### 运行 Migrations

```bash
# 在 Supabase SQL Editor 中按顺序运行：
1. 013_auto_create_user_on_signup.sql
2. 014_add_brands_table.sql
3. 015_add_categories_tree.sql
4. 016_add_products_catalog.sql
5. 017_link_receipt_items_to_products.sql
6. 018_add_price_snapshots.sql
```

### 验证安装

```sql
-- 检查所有表是否创建成功
SELECT tablename 
FROM pg_tables 
WHERE schemaname = 'public' 
  AND tablename IN (
    'brands', 
    'categories', 
    'products', 
    'price_snapshots'
  )
ORDER BY tablename;

-- 预期结果：4 rows
```

---

## 💡 关键概念

### OLTP vs OLAP

**LedgerLens 的双重身份：**

```
OLTP (交易层):
  receipt_items → 快速写入，保留原始数据
  
OLAP (分析层):
  products, categories, price_snapshots → 聚合查询，优化读取
```

### Normalization vs Denormalization

**Normalization (减少冗余):**
```sql
-- ✅ 正确：brand 存在 brands 表
products.brand_id → brands.id

-- ❌ 错误：每行都存 brand name
receipt_items.brand_name TEXT
```

**Denormalization (优化查询):**
```sql
-- ✅ 正确：receipt_items 保留原始 product_name
receipt_items.product_name TEXT  -- 原始 OCR 结果
receipt_items.product_id UUID    -- 标准化后的商品

-- 原因：
-- 1. 调试时需要看原始名称
-- 2. OCR 错误时需要人工审核
-- 3. 商品归一化可能有误，保留原始数据
```

---

## ⚠️ 注意事项

### 1. 不要立即删除 category_l1/l2/l3

保留这些列用于：
- 向后兼容
- 数据验证
- 渐进式迁移

等 category_id 完全填充后再考虑删除。

### 2. product_id 的 backfill 需要 LLM

不能用简单的 SQL 自动 backfill，因为需要：
- 商品名称归一化（"BANANA" → "banana"）
- 品牌识别
- 分类匹配

建议通过 Python 脚本 + LLM 完成。

### 3. Price Snapshots 的数据质量

confidence_score 基于：
- 样本数量
- 贡献者数量
- 数据新鲜度

低置信度的价格应该在 UI 上标注或隐藏。

---

## 🎯 成功标准

### Migration 成功后应该能：

1. ✅ 创建新品牌
2. ✅ 创建新分类
3. ✅ 创建新商品
4. ✅ 将小票商品链接到标准化商品
5. ✅ 按商品聚合用户花费
6. ✅ 按分类聚合用户花费
7. ✅ 查询商品在不同店的价格（PricePeek）

### Dashboard 应该能显示：

```
📊 月度花费
  - Grocery: $1,234
    - Produce: $456
      - Fruit: $234
    - Dairy: $567

📦 购买最多的商品
  1. Banana (Dole) - 15次 - $23.45
  2. Milk (Horizon) - 12次 - $59.88
  3. ...

🏷️ 品牌分析
  - Dole: $89.34 (23 items)
  - Horizon: $124.67 (18 items)
  
💰 本月 Sale 节省
  - Total saved: $45.67
  - 12 items on sale
```

---

## 📞 Support

如果遇到问题：
1. 检查 `MIGRATIONS_ORDER.md` 确认运行顺序
2. 查看 migration 文件中的 Comments 和 Example queries
3. 运行 verification queries 检查数据完整性
