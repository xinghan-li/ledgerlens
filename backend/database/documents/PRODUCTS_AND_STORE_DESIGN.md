# Products 表与 store_chain_id 设计说明

## products 表的 store_chain_id（Migration 029 起）

- **products** 唯一键：`(normalized_name, size_quantity, size_unit, package_type, store_chain_id)`
- `store_chain_id` 可空：NULL 表示 legacy/全局，唯一索引用 sentinel UUID 将 NULL 视为同一 bucket
- **目的**：同一名称+规格在不同商家视为不同 product（如沃尔玛 naan vs 缺德舅 naan）；香蕉等跨店统一商品可后续再考虑合并策略

## product_categorization_rules 的 store_chain_id

- 规则表有 `store_chain_id`，表示「某商家下，某商品名 → 某分类」
- 同一商品名在不同商家可对应不同分类

## store 归属

- record_items → receipt_id → record_summaries.store_chain_id；product 行自身也带 store_chain_id，与唯一键一致
