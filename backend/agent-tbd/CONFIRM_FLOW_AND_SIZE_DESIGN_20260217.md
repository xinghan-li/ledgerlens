# Confirm 数据流检查 & Size/Unit/Package 设计

## 0. 已实现 (2026-02-17)

- **Migration 027**：products、classification_review 拆分为 size_quantity、size_unit、package_type
- **Confirm 时回填**：source_record_item 的 product_id、product_name_clean
- **前端**：分类审核表格三列 size_qty / unit / package，blur 时 PATCH

## 1. Classification Review Confirm 后的数据流

### 会正确更新的表

| 表 | 行为 |
|----|------|
| **product_categorization_rules** | ✅ 写入或 upsert (normalized_name, store_chain_id, category_id, match_type) |
| **products** | ✅ 写入或更新 (normalized_name, size, unit_type, category_id)，unique 键为 (normalized_name, size) |
| **classification_review** | ✅ status=confirmed, confirmed_at, confirmed_by |

### 不会更新的表

| 表 | 原因 |
|----|------|
| **categories** | 只引用已有 category_id，不做创建或修改 |
| **price_snapshots** | 由 `aggregate_prices_for_date()` 从 record_items 聚合，依赖 `record_items.product_id` |
| **record_items** | confirm 不回填 source_record_item 的 product_id |

### 潜在问题

1. **record_items.product_id**  
   当前 save_receipt_items 不会设置 product_id，confirm 也不会回填。price_snapshots 依赖 record_items 有 product_id，因此目前价格聚合不会产生数据。

2. **product_categorization_rules 未被读取**  
   保存 record_items 时只用 LLM 的 category 做 _resolve_category_id，未查 product_categorization_rules 或 products 来填充 product_id。

### 结论

- product_categorization_rules 和 products 会正确写入。
- categories 只是引用，无变更。
- price_snapshots 不会因为 confirm 而更新，需要后续实现 record_items.product_id 的匹配与回填逻辑。

---

## 2. Size / Unit / Package 存储设计建议

### 当前结构 (products)

- `size` (TEXT): e.g. "3.5 oz", "1 gallon"
- `unit_type` (TEXT): e.g. "oz", "gallon"

### 建议结构：quantity / unit / package_type

| 列 | 类型 | 示例 | 用途 |
|----|------|------|------|
| **size_quantity** | NUMERIC | 3.5 | 数值比较、单位换算 |
| **size_unit** | TEXT | oz | 单位（oz, ml, lb, g, ct 等） |
| **package_type** | TEXT | bottle | 包装类型（bottle, box, bag, jar, can, pouch 等） |

**优势：**

- 单位换算：3.5 oz ↔ 103.5 ml
- 可比性：按 price per oz 排序
- 可扩展：package_type 独立，便于筛选（如 “所有瓶装”）

### 向后兼容

- 可保留 `size` (TEXT) 作为展示用：`"3.5 oz / bottle"` 由 size_quantity + size_unit + package_type 生成
- 或迁移：`size` → `size_quantity`, `unit_type` → `size_unit`，新增 `package_type`

### 实施

需要 migration 修改 products、classification_review 及相关写入/读取逻辑。
