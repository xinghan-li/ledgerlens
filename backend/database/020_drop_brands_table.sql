-- ============================================
-- Migration 020: Drop brands table (MVP simplification)
-- ============================================
-- Purpose: Deprecate brands table per MVP principle - high maintenance, low benefit.
--
-- DECISION: 2026-02-12 - Brands table deprecated. Run this migration to remove
-- brands and all references (products.brand_id). See deprecated/014_add_brands_table.sql
--
-- Prerequisites: 016 (products), 017 (view), 018 (materialized view) - run in order
-- ============================================

BEGIN;

-- 0. Drop views that reference brands (017, 018)
DROP MATERIALIZED VIEW IF EXISTS latest_prices;
DROP VIEW IF EXISTS receipt_items_enriched;

-- 1. Drop products unique constraint (references brand_id)
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_unique_key;

-- 2. Drop brand_id column from products (drops FK and products_brand_idx automatically)
ALTER TABLE products DROP COLUMN IF EXISTS brand_id;

-- 3. Re-add unique constraint without brand_id (skip if duplicates exist)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM products
    GROUP BY normalized_name, size, variant_type
    HAVING COUNT(*) > 1
  ) THEN
    ALTER TABLE products ADD CONSTRAINT products_unique_key
      UNIQUE(normalized_name, size, variant_type);
  ELSE
    RAISE NOTICE 'Skipping products_unique_key - duplicate (normalized_name, size, variant_type) exist';
  END IF;
END $$;

-- 4. Drop brands table
DROP TABLE IF EXISTS brands CASCADE;

-- 5. Recreate views without brands reference
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

CREATE MATERIALIZED VIEW latest_prices AS
SELECT DISTINCT ON (product_id, store_location_id)
  ps.id,
  ps.product_id,
  ps.store_location_id,
  ps.latest_price_cents,
  ps.snapshot_date,
  ps.last_seen_date,
  ps.sample_count,
  ps.is_on_sale,
  ps.confidence_score,
  p.normalized_name as product_name,
  sl.name as store_name,
  sl.city,
  sl.state
FROM price_snapshots ps
JOIN products p ON ps.product_id = p.id
JOIN store_locations sl ON ps.store_location_id = sl.id
ORDER BY product_id, store_location_id, snapshot_date DESC;

CREATE UNIQUE INDEX latest_prices_product_location_idx ON latest_prices(product_id, store_location_id);
CREATE INDEX latest_prices_product_idx ON latest_prices(product_id);
CREATE INDEX latest_prices_location_idx ON latest_prices(store_location_id);
CREATE INDEX latest_prices_price_idx ON latest_prices(latest_price_cents);
COMMENT ON MATERIALIZED VIEW latest_prices IS 'Quick lookup for latest price of each product at each store (refresh daily)';

COMMIT;

-- ============================================
-- Verification
-- ============================================
DO $$
BEGIN
  RAISE NOTICE 'Migration 020 completed: brands table dropped, products.brand_id removed';
END $$;
