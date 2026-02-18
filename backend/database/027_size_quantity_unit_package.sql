-- ============================================
-- Migration 027: Split size into size_quantity, size_unit, package_type
-- ============================================
-- Purpose: Store size as quantity/unit/package for unit conversion and comparison.
-- Format: 3.5 / oz / bottle
--
-- Run after: 022, 025
-- ============================================

BEGIN;

-- ============================================
-- 1. products: add new columns, migrate, drop old, add unique
-- ============================================
ALTER TABLE products
  ADD COLUMN IF NOT EXISTS size_quantity NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS size_unit TEXT,
  ADD COLUMN IF NOT EXISTS package_type TEXT;

-- Best-effort migrate from size/unit_type (e.g. "3.5 oz" -> 3.5, "oz")
UPDATE products
SET
  size_quantity = CASE WHEN size ~ '^\d+\.?\d*' THEN (regexp_match(size, '^(\d+\.?\d*)'))[1]::NUMERIC ELSE NULL END,
  size_unit = COALESCE(unit_type, CASE WHEN size ~ '^\d+\.?\d*\s+[a-zA-Z]+' THEN (regexp_match(size, '^\d+\.?\d*\s+([a-zA-Z]+)'))[1] ELSE NULL END)
WHERE size IS NOT NULL OR unit_type IS NOT NULL;

-- Drop old unique and columns
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unique_key;
ALTER TABLE products DROP COLUMN IF EXISTS size;
ALTER TABLE products DROP COLUMN IF EXISTS unit_type;

-- New unique: (normalized_name, size_quantity, size_unit, package_type)
ALTER TABLE products ADD CONSTRAINT products_unique_key
  UNIQUE(normalized_name, size_quantity, size_unit, package_type);

COMMENT ON COLUMN products.size_quantity IS 'Numeric quantity (e.g. 3.5)';
COMMENT ON COLUMN products.size_unit IS 'Unit of measure (oz, ml, lb, ct, etc.)';
COMMENT ON COLUMN products.package_type IS 'Package type (bottle, box, bag, jar, can, etc.)';

-- ============================================
-- 2. classification_review: add new columns, drop old
-- ============================================
ALTER TABLE classification_review
  ADD COLUMN IF NOT EXISTS size_quantity NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS size_unit TEXT,
  ADD COLUMN IF NOT EXISTS package_type TEXT;

ALTER TABLE classification_review DROP COLUMN IF EXISTS size;
ALTER TABLE classification_review DROP COLUMN IF EXISTS unit_type;

COMMENT ON COLUMN classification_review.size_quantity IS 'Numeric quantity (e.g. 3.5)';
COMMENT ON COLUMN classification_review.size_unit IS 'Unit of measure (oz, ml, lb, ct, etc.)';
COMMENT ON COLUMN classification_review.package_type IS 'Package type (bottle, box, bag, jar, can, etc.)';

-- ============================================
-- 3. Update views/functions that reference products.size, products.unit_type
-- ============================================
DROP VIEW IF EXISTS record_items_enriched;
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
  RAISE NOTICE 'Migration 027 completed: size_quantity, size_unit, package_type';
END $$;
