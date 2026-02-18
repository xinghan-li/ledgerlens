-- ============================================
-- Migration 029: size_quantity 2 decimals + products unique by store_chain_id
-- ============================================
-- 1. size_quantity: NUMERIC(12,4) -> NUMERIC(12,2) on products and classification_review
-- 2. products: add store_chain_id, unique (normalized_name, size_quantity, size_unit, package_type, store_chain_id)
--    NULL store_chain_id treated as one bucket via unique index expression
--
-- Run after: 027, 028
-- ============================================

BEGIN;

-- ============================================
-- 0. Drop view that depends on products.size_quantity (recreate after alter)
-- ============================================
DROP VIEW IF EXISTS record_items_enriched;

-- ============================================
-- 1. size_quantity: two decimal places
-- ============================================
ALTER TABLE products
  ALTER COLUMN size_quantity TYPE NUMERIC(12,2) USING ROUND(size_quantity, 2);

ALTER TABLE classification_review
  ALTER COLUMN size_quantity TYPE NUMERIC(12,2) USING ROUND(size_quantity, 2);

COMMENT ON COLUMN products.size_quantity IS 'Numeric quantity, 2 decimal places (e.g. 3.5)';
COMMENT ON COLUMN classification_review.size_quantity IS 'Numeric quantity, 2 decimal places (e.g. 3.5)';

-- ============================================
-- 2. products: add store_chain_id
-- ============================================
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS store_chain_id UUID REFERENCES store_chains(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS products_store_chain_id_idx ON products(store_chain_id) WHERE store_chain_id IS NOT NULL;

COMMENT ON COLUMN products.store_chain_id IS 'Store chain for this product; NULL = legacy/global';

-- ============================================
-- 3. Replace unique constraint with index (NULL store_chain_id = one bucket)
-- ============================================
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unique_key;

-- Sentinel UUID for "no store": all NULL store_chain_id count as same key
CREATE UNIQUE INDEX products_unique_key ON products (
  normalized_name,
  size_quantity,
  size_unit,
  package_type,
  COALESCE(store_chain_id, '00000000-0000-0000-0000-000000000000'::uuid)
);

-- ============================================
-- 4. Recreate view (depends on products.size_quantity, etc.)
-- ============================================
CREATE OR REPLACE VIEW record_items_enriched AS
SELECT
  ri.id, ri.receipt_id, ri.user_id,
  ri.product_name as raw_product_name,
  p.normalized_name as product_normalized_name,
  p.size_quantity as product_size_quantity,
  p.size_unit as product_size_unit,
  p.package_type as product_package_type,
  c1.name as category_l1, c2.name as category_l2, c3.name as category_l3,
  COALESCE(ri.category_id, p.category_id) as category_id,
  ri.quantity, ri.unit, ri.unit_price, ri.line_total, ri.on_sale, ri.discount_amount,
  rs.store_chain_id, rs.store_location_id,
  sc.name as store_chain_name, sl.name as store_location_name,
  rs.receipt_date, ri.created_at
FROM record_items ri
LEFT JOIN products p ON ri.product_id = p.id
LEFT JOIN categories c3 ON COALESCE(ri.category_id, p.category_id) = c3.id
LEFT JOIN categories c2 ON c3.parent_id = c2.id
LEFT JOIN categories c1 ON c2.parent_id = c1.id
LEFT JOIN receipt_status r ON ri.receipt_id = r.id
LEFT JOIN record_summaries rs ON r.id = rs.receipt_id
LEFT JOIN store_chains sc ON rs.store_chain_id = sc.id
LEFT JOIN store_locations sl ON rs.store_location_id = sl.id;

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 029 completed: size_quantity NUMERIC(12,2); products unique by (normalized_name, size_quantity, size_unit, package_type, store_chain_id)';
END $$;
