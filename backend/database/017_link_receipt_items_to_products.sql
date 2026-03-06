-- ============================================
-- Migration 017: record_items 关联 products/categories + record_items_enriched 视图
--
-- 原来此文件还 ADD COLUMN product_id / category_id。
-- 由于 products(016) 和 categories(015) 在 012 之后建，FK 无法提前加，
-- 故这两列仍在本文件添加。
--
-- 视图使用 products 最终列名（size_quantity/size_unit/package_type），
-- 合并了原来 020/021/022/027/029 里多次 DROP+CREATE 视图的操作——
-- 新库里只在此处建一次。
--
-- PREREQUISITES: 012, 015, 016
-- ============================================

BEGIN;

-- ============================================
-- 1. record_items 增加 product_id / category_id FK
-- ============================================
ALTER TABLE record_items
  ADD COLUMN product_id UUID REFERENCES products(id) ON DELETE SET NULL;

ALTER TABLE record_items
  ADD COLUMN category_id UUID REFERENCES categories(id) ON DELETE SET NULL;

-- 索引
CREATE INDEX record_items_product_id_idx ON record_items(product_id);
CREATE INDEX record_items_category_id_idx ON record_items(category_id);
CREATE INDEX record_items_user_product_idx ON record_items(user_id, product_id);
CREATE INDEX record_items_product_date_idx ON record_items(product_id, created_at DESC);
CREATE INDEX record_items_user_category_idx ON record_items(user_id, category_id);

COMMENT ON COLUMN record_items.product_id IS 'FK to products for normalized product aggregation';
COMMENT ON COLUMN record_items.category_id IS 'FK to categories (level-3/leaf). L1/L2 via JOIN.';

-- ============================================
-- 2. record_items_enriched 视图（最终形态，仅建一次）
--    合并了 020/021/022/027/029 里多次 DROP+CREATE 的结果
-- ============================================
CREATE OR REPLACE VIEW record_items_enriched AS
SELECT
  ri.id,
  ri.receipt_id,
  ri.user_id,
  ri.product_name AS raw_product_name,
  p.normalized_name AS product_normalized_name,
  p.size_quantity AS product_size_quantity,
  p.size_unit AS product_size_unit,
  p.package_type AS product_package_type,
  c1.name AS category_l1,
  c2.name AS category_l2,
  c3.name AS category_l3,
  COALESCE(ri.category_id, p.category_id) AS category_id,
  ri.quantity,
  ri.unit,
  ri.unit_price,
  ri.line_total,
  ri.on_sale,
  ri.discount_amount,
  rs.store_chain_id,
  rs.store_location_id,
  sc.name AS store_chain_name,
  sl.name AS store_location_name,
  rs.receipt_date,
  ri.created_at
FROM record_items ri
LEFT JOIN products p ON ri.product_id = p.id
LEFT JOIN categories c3 ON COALESCE(ri.category_id, p.category_id) = c3.id
LEFT JOIN categories c2 ON c3.parent_id = c2.id
LEFT JOIN categories c1 ON c2.parent_id = c1.id
LEFT JOIN receipt_status r ON ri.receipt_id = r.id
LEFT JOIN record_summaries rs ON r.id = rs.receipt_id
LEFT JOIN store_chains sc ON rs.store_chain_id = sc.id
LEFT JOIN store_locations sl ON rs.store_location_id = sl.id;

COMMENT ON VIEW record_items_enriched IS 'Enriched view of record_items with product, category, and store info';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 017 completed: product_id/category_id added to record_items; record_items_enriched view created (final form)';
END $$;
