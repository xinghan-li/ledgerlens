# Store-Specific Categorization Rules

## 📋 概述

为了解决同一个商品在不同商店分类可能不同的问题（例如 Naan 在 Costco 是 Bakery，在 T&T 是 Frozen），我们实现了 **Store-Specific 规则系统**。

## 🎯 问题示例

同一个商品在不同商店的分类不同：

| 商品 | Costco | T&T (Asian Supermarket) | Walmart |
|------|--------|------------------------|---------|
| Naan | Bakery（新鲜面包区） | Frozen（冷冻食品） | Deli（熟食） |
| Chicken | Meat & Seafood（生鲜） | Frozen/Prepared（炸鸡） | Meat & Seafood（生鲜） |
| Dumpling | Frozen | Frozen | Deli |

## 🏗️ 解决方案

### 1. **规则表支持 Store-Specific**

`product_categorization_rules` 表新增 `store_chain_id` 字段：
- **NULL**: 通用规则（适用于所有商店）
- **Non-NULL**: Store-specific 规则（只适用于特定商店链）

```sql
CREATE TABLE product_categorization_rules (
  normalized_name TEXT NOT NULL,
  store_chain_id UUID REFERENCES store_chains(id),  -- NULL = 通用规则
  category_id UUID NOT NULL,
  priority INT DEFAULT 100,
  ...
);
```

### 2. **查询优先级**

`find_categorization_rule()` 函数会按以下顺序查找：

1. **Store-specific 精确匹配**（最高优先级）
2. **通用精确匹配**
3. **Store-specific 模糊匹配**（90% 相似度）
4. **通用模糊匹配**
5. **Store-specific contains 匹配**
6. **通用 contains 匹配**
7. **关键词 fallback**（最低优先级）

### 3. **CSV 格式更新**

Summary CSV 新增 `store_name` 列：

```csv
normalized_name,store_name,count,original_names,brands,category_l1,category_l2,category_l3,example_price
banana,T&T,3,BANANA,Dole,Grocery,Produce,Fruit,0.23
naan,Costco,2,NAAN | GARLIC NAAN,,Grocery,Bakery,,2.99
naan,T&T,1,FROZEN NAAN,,Grocery,Frozen,,3.49
```

**注意**：
- 同一个 `normalized_name` 在不同 `store_name` 下会分开统计
- 这样你可以为每个商店分别设置分类

## 🔄 工作流程

### 第 1 步：运行 Migration

```bash
# 在 Supabase SQL Editor 中运行
f:\LedgerLens\backend\database\019_add_categorization_rules.sql
```

### 第 2 步：修正 CSV

打开生成的 Summary CSV：
```
f:\LedgerLens\output\standardization_preview\standardization_summary_<timestamp>.csv
```

修正分类，注意 `store_name` 列：
- 如果同一商品在不同商店分类不同，保留两行分别修正
- 如果在所有商店分类相同，保留一行即可（会创建通用规则）

### 第 3 步：导入规则

```bash
cd f:\LedgerLens\backend
python import_category_rules.py --csv ../output/standardization_preview/standardization_summary_corrected.csv
```

脚本会：
- 查找 `store_name` 对应的 `store_chain_id`
- 如果找到，创建 **store-specific 规则**（优先级 40）
- 如果未找到，创建 **通用规则**（优先级 50）

### 第 4 步：验证

```bash
python generate_standardization_preview.py
```

查看新生成的 CSV，验证分类是否正确应用。

## 💡 使用建议

### 1. **优先创建通用规则**

第一次导入时，大部分商品应该创建通用规则：
- 只有在明确知道某商品在特定商店分类不同时，才创建 store-specific 规则
- 通用规则覆盖面更广，维护成本更低

### 2. **渐进式优化**

- 第一轮：只改通用商品（如 Banana, Milk），适用于所有商店
- 第二轮：发现分类不对的 store-specific 商品（如 Naan），单独修正

### 3. **Store Name 标准化**

确保 `store_name` 与 `store_chains` 表中的名称一致：
```sql
SELECT name FROM store_chains;
```

常见商店名称：
- Costco
- T&T Supermarket
- Walmart
- Save-On-Foods
- etc.

## 📊 规则优先级说明

| 规则类型 | Priority | 说明 |
|---------|----------|------|
| Store-specific (manual) | 40 | 用户手动创建的 store-specific 规则，最高优先级 |
| Universal (manual) | 50 | 用户手动创建的通用规则 |
| Auto-learned | 100 | 系统自动学习的规则（未来功能） |

## 🔍 示例

### 示例 1：通用规则

CSV：
```csv
normalized_name,store_name,count,category_l1,category_l2,category_l3
banana,,10,Grocery,Produce,Fruit
```

结果：
- 创建通用规则：`banana` → `Grocery/Produce/Fruit`
- 适用于所有商店

### 示例 2：Store-Specific 规则

CSV：
```csv
normalized_name,store_name,count,category_l1,category_l2,category_l3
naan,Costco,5,Grocery,Bakery,
naan,T&T,3,Grocery,Frozen,
```

结果：
- 创建 2 条规则：
  1. `naan` @ Costco → `Grocery/Bakery` (优先级 40)
  2. `naan` @ T&T → `Grocery/Frozen` (优先级 40)
  
查询行为：
- 处理 Costco 小票：`naan` → `Bakery` ✅
- 处理 T&T 小票：`naan` → `Frozen` ✅
- 处理其他商店小票：`naan` → fallback 到关键词匹配

## 🚀 下一步

1. 运行 Migration 019
2. 修正 CSV（按 store_name 分组）
3. 导入规则
4. 验证效果
5. 迭代优化

---

**注意**：Migration 019 必须在 Migration 015 (categories tree) 之后运行。
