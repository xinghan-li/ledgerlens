-- ============================================
-- Migration 030: Atomic increment for products.usage_count
-- ============================================
-- Purpose: Avoid race condition when multiple confirms update the same product.
-- Call from classification_review confirm instead of read-then-write usage_count.
--
-- Run after: 029
-- ============================================

BEGIN;

CREATE OR REPLACE FUNCTION increment_product_usage(
  p_product_id UUID,
  p_category_id UUID DEFAULT NULL,
  p_last_seen_date DATE DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
  UPDATE products
  SET
    usage_count = usage_count + 1,
    category_id = COALESCE(p_category_id, category_id),
    last_seen_date = COALESCE(p_last_seen_date, last_seen_date)
  WHERE id = p_product_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION increment_product_usage IS 'Atomically increment usage_count and optionally set category_id/last_seen_date for a product';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 030 completed: increment_product_usage() RPC created';
END $$;
