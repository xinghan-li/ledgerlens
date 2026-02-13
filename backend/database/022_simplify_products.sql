-- ============================================
-- Migration 022: Simplify products table (MVP)
-- ============================================
-- Purpose: Remove columns that are hard to obtain or maintain for solo dev.
--
-- Run after: 016, 017, 018, 019, 020
--
-- 保留字段 | Kept (per DB_DEFINITIONS):
--   id, normalized_name, size, unit_type, category_id,
--   usage_count, last_seen_date, created_at, updated_at
--
-- 删除字段 | Removed:
--   brand_id         - already dropped by 020
--   variant_type     - hard to maintain
--   is_organic       - hard to obtain
--   aliases          - hard to maintain
--   search_keywords  - hard to maintain
--   description      - hard to obtain
--   image_url        - hard to obtain
--   barcode          - hard to obtain
-- ============================================

BEGIN;

-- 0. Drop views that reference products columns we're removing
DROP VIEW IF EXISTS receipt_items_enriched;

-- 1. Drop unique constraint (may include variant_type)
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unique_key;

-- 2. Drop columns (IF EXISTS for brand_id in case 020 already dropped it)
ALTER TABLE products
  DROP COLUMN IF EXISTS brand_id,
  DROP COLUMN IF EXISTS variant_type,
  DROP COLUMN IF EXISTS is_organic,
  DROP COLUMN IF EXISTS aliases,
  DROP COLUMN IF EXISTS search_keywords,
  DROP COLUMN IF EXISTS description,
  DROP COLUMN IF EXISTS image_url,
  DROP COLUMN IF EXISTS barcode;

-- 3. Re-add unique constraint
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM products
    GROUP BY normalized_name, size
    HAVING COUNT(*) > 1
  ) THEN
    ALTER TABLE products ADD CONSTRAINT products_unique_key
      UNIQUE(normalized_name, size);
  ELSE
    RAISE NOTICE 'Skipping products_unique_key - duplicate (normalized_name, size) exist';
  END IF;
END $$;

-- 4. Recreate receipt_items_enriched (without is_organic, etc.)
CREATE OR REPLACE VIEW receipt_items_enriched AS
SELECT 
  ri.id,
  ri.receipt_id,
  ri.user_id,
  ri.product_name as raw_product_name,
  p.normalized_name as product_normalized_name,
  p.size as product_size,
  p.unit_type as product_unit_type,
  c1.name as category_l1,
  c2.name as category_l2,
  c3.name as category_l3,
  COALESCE(ri.category_id, p.category_id) as category_id,
  ri.quantity,
  ri.unit,
  ri.unit_price,
  ri.line_total,
  ri.on_sale,
  ri.discount_amount,
  rs.store_chain_id,
  rs.store_location_id,
  sc.name as store_chain_name,
  sl.name as store_location_name,
  rs.receipt_date,
  ri.created_at
FROM receipt_items ri
LEFT JOIN products p ON ri.product_id = p.id
LEFT JOIN categories c3 ON COALESCE(ri.category_id, p.category_id) = c3.id
LEFT JOIN categories c2 ON c3.parent_id = c2.id
LEFT JOIN categories c1 ON c2.parent_id = c1.id
LEFT JOIN receipts r ON ri.receipt_id = r.id
LEFT JOIN receipt_summaries rs ON r.id = rs.receipt_id
LEFT JOIN store_chains sc ON rs.store_chain_id = sc.id
LEFT JOIN store_locations sl ON rs.store_location_id = sl.id;

COMMENT ON VIEW receipt_items_enriched IS 'Enriched view of receipt_items with product, category, and store information';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 022 completed: products table simplified';
END $$;
