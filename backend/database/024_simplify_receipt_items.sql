-- ============================================
-- Migration 024: Simplify record_items (MVP)
-- ============================================
-- Purpose: Streamline record_items for MVP - integer-only storage, single category_id,
-- remove brand, ocr metadata, and record_items_enriched view.
--
-- Run after: 012, 017, 018, 021
--
-- Changes:
-- 1. Drop record_items_enriched view (MVP doesn't need it; add back at scale)
-- 2. Drop brand - too hard to maintain
-- 3. Drop category_l1, category_l2, category_l3 - keep only category_id (level-3 FK)
-- 4. Drop ocr_coordinates, ocr_confidence - incoming data is validated
-- 5. All numeric fields x100: quantity, unit_price, line_total, original_price, discount_amount
--    - quantity: 1.5 -> 150, 2 -> 200 (BIGINT)
--    - unit_price, line_total, etc.: dollars -> cents (BIGINT)
-- ============================================

BEGIN;

-- ============================================
-- 1. Drop record_items_enriched (MVP: add back when 1000+ records)
-- ============================================
DROP VIEW IF EXISTS record_items_enriched;

-- ============================================
-- 2. Drop columns
-- ============================================
ALTER TABLE record_items
  DROP COLUMN IF EXISTS brand,
  DROP COLUMN IF EXISTS category_l1,
  DROP COLUMN IF EXISTS category_l2,
  DROP COLUMN IF EXISTS category_l3,
  DROP COLUMN IF EXISTS ocr_coordinates,
  DROP COLUMN IF EXISTS ocr_confidence;

-- ============================================
-- 3. Drop indexes on removed columns
-- ============================================
DROP INDEX IF EXISTS record_items_category_l1_idx;
DROP INDEX IF EXISTS record_items_category_l2_idx;
DROP INDEX IF EXISTS record_items_category_l3_idx;

-- ============================================
-- 4. Migrate numeric columns to integers (x100)
-- ============================================
-- Add new columns as BIGINT, backfill, drop old, rename
-- quantity: NUMERIC(10,3) -> BIGINT (x100, e.g. 1.5 -> 150). NULL stays NULL.
ALTER TABLE record_items ADD COLUMN quantity_x100 BIGINT;
UPDATE record_items SET quantity_x100 = ROUND(quantity * 100)::BIGINT WHERE quantity IS NOT NULL;
ALTER TABLE record_items DROP COLUMN quantity;
ALTER TABLE record_items RENAME COLUMN quantity_x100 TO quantity;

-- unit_price: NUMERIC(10,2) -> BIGINT (cents)
ALTER TABLE record_items ADD COLUMN unit_price_cents BIGINT;
UPDATE record_items SET unit_price_cents = ROUND(unit_price * 100)::BIGINT WHERE unit_price IS NOT NULL;
ALTER TABLE record_items DROP COLUMN unit_price;
ALTER TABLE record_items RENAME COLUMN unit_price_cents TO unit_price;

-- line_total: NUMERIC(10,2) -> BIGINT (cents)
ALTER TABLE record_items ADD COLUMN line_total_cents BIGINT;
UPDATE record_items SET line_total_cents = ROUND(line_total * 100)::BIGINT;
ALTER TABLE record_items DROP COLUMN line_total;
ALTER TABLE record_items RENAME COLUMN line_total_cents TO line_total;
ALTER TABLE record_items ALTER COLUMN line_total SET NOT NULL;

-- original_price: NUMERIC(10,2) -> BIGINT (cents)
ALTER TABLE record_items ADD COLUMN original_price_cents BIGINT;
UPDATE record_items SET original_price_cents = ROUND(original_price * 100)::BIGINT WHERE original_price IS NOT NULL;
ALTER TABLE record_items DROP COLUMN original_price;
ALTER TABLE record_items RENAME COLUMN original_price_cents TO original_price;

-- discount_amount: NUMERIC(10,2) -> BIGINT (cents)
ALTER TABLE record_items ADD COLUMN discount_amount_cents BIGINT;
UPDATE record_items SET discount_amount_cents = ROUND(discount_amount * 100)::BIGINT WHERE discount_amount IS NOT NULL;
ALTER TABLE record_items DROP COLUMN discount_amount;
ALTER TABLE record_items RENAME COLUMN discount_amount_cents TO discount_amount;

-- ============================================
-- 5. Update constraints
-- ============================================
ALTER TABLE record_items DROP CONSTRAINT IF EXISTS record_items_quantity_check;
ALTER TABLE record_items DROP CONSTRAINT IF EXISTS record_items_unit_price_check;
ALTER TABLE record_items DROP CONSTRAINT IF EXISTS record_items_line_total_check;
ALTER TABLE record_items DROP CONSTRAINT IF EXISTS record_items_ocr_confidence_check;

ALTER TABLE record_items ADD CONSTRAINT record_items_quantity_check
  CHECK (quantity IS NULL OR quantity >= 0);
ALTER TABLE record_items ADD CONSTRAINT record_items_unit_price_check
  CHECK (unit_price IS NULL OR unit_price >= 0);
ALTER TABLE record_items ADD CONSTRAINT record_items_line_total_check
  CHECK (line_total >= 0);

-- ============================================
-- 6. Update aggregate_prices_for_date (018)
--    unit_price and discount_amount are now already in cents
-- ============================================
CREATE OR REPLACE FUNCTION aggregate_prices_for_date(target_date DATE)
RETURNS INT AS $$
DECLARE
  rows_inserted INT := 0;
BEGIN
  INSERT INTO price_snapshots (
    product_id,
    store_location_id,
    latest_price_cents,
    snapshot_date,
    last_seen_date,
    sample_count,
    avg_price_cents,
    min_price_cents,
    max_price_cents,
    is_on_sale,
    sale_count,
    avg_discount_cents,
    contributor_count,
    confidence_score,
    data_quality
  )
  SELECT
    ri.product_id,
    rs.store_location_id,
    (ARRAY_AGG(ri.unit_price::INT ORDER BY rs.receipt_date DESC))[1] as latest_price_cents,
    target_date as snapshot_date,
    MAX(rs.receipt_date) as last_seen_date,
    COUNT(*) as sample_count,
    ROUND(AVG(ri.unit_price))::INT as avg_price_cents,
    MIN(ri.unit_price)::INT as min_price_cents,
    MAX(ri.unit_price)::INT as max_price_cents,
    BOOL_OR(ri.on_sale) as is_on_sale,
    COUNT(*) FILTER (WHERE ri.on_sale) as sale_count,
    ROUND(AVG(ri.discount_amount) FILTER (WHERE ri.on_sale))::INT as avg_discount_cents,
    COUNT(DISTINCT ri.user_id) as contributor_count,
    CASE 
      WHEN COUNT(*) >= 20 THEN 1.0
      WHEN COUNT(*) >= 10 THEN 0.9
      WHEN COUNT(*) >= 5 THEN 0.8
      WHEN COUNT(*) >= 2 THEN 0.6
      ELSE 0.4
    END as confidence_score,
    CASE
      WHEN COUNT(*) >= 10 AND COUNT(DISTINCT ri.user_id) >= 3 THEN 'high'
      WHEN COUNT(*) >= 5 AND COUNT(DISTINCT ri.user_id) >= 2 THEN 'medium'
      ELSE 'low'
    END as data_quality
  FROM record_items ri
  JOIN receipt_status r ON ri.receipt_id = r.id
  JOIN record_summaries rs ON r.id = rs.receipt_id
  WHERE ri.product_id IS NOT NULL
    AND rs.store_location_id IS NOT NULL
    AND rs.receipt_date = target_date
    AND ri.unit_price IS NOT NULL
    AND ri.unit_price > 0
  GROUP BY ri.product_id, rs.store_location_id
  ON CONFLICT (product_id, store_location_id, snapshot_date) 
  DO UPDATE SET
    latest_price_cents = EXCLUDED.latest_price_cents,
    last_seen_date = EXCLUDED.last_seen_date,
    sample_count = price_snapshots.sample_count + EXCLUDED.sample_count,
    avg_price_cents = EXCLUDED.avg_price_cents,
    min_price_cents = LEAST(price_snapshots.min_price_cents, EXCLUDED.min_price_cents),
    max_price_cents = GREATEST(price_snapshots.max_price_cents, EXCLUDED.max_price_cents),
    is_on_sale = EXCLUDED.is_on_sale,
    sale_count = price_snapshots.sale_count + EXCLUDED.sale_count,
    avg_discount_cents = EXCLUDED.avg_discount_cents,
    contributor_count = EXCLUDED.contributor_count,
    confidence_score = EXCLUDED.confidence_score,
    data_quality = EXCLUDED.data_quality,
    updated_at = NOW();
  
  GET DIAGNOSTICS rows_inserted = ROW_COUNT;
  
  BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY latest_prices;
  EXCEPTION WHEN OTHERS THEN
    REFRESH MATERIALIZED VIEW latest_prices;
  END;
  
  RETURN rows_inserted;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- 7. Comments
-- ============================================
COMMENT ON COLUMN record_items.quantity IS 'Quantity x100 (e.g. 1.5 -> 150, 2 -> 200). No decimals.';
COMMENT ON COLUMN record_items.unit_price IS 'Unit price in cents. No decimals.';
COMMENT ON COLUMN record_items.line_total IS 'Line total in cents. No decimals.';
COMMENT ON COLUMN record_items.original_price IS 'Original price before discount, in cents.';
COMMENT ON COLUMN record_items.discount_amount IS 'Discount amount in cents.';
COMMENT ON COLUMN record_items.category_id IS 'FK to categories (level-3/leaf). L1/L2 via JOIN.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 024 completed: record_items simplified (brand, category_l1/2/3, ocr_* removed; quantities/prices x100; record_items_enriched dropped)';
END $$;
