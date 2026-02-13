-- ============================================
-- Migration 017: Link record_items to products catalog
-- ============================================
-- Purpose: Add product_id foreign key to record_items to enable
-- cross-receipt product aggregation
--
-- This enables:
-- 1. "How much did I spend on Dole Banana across all receipts?"
-- 2. "What's my average price for milk?"
-- 3. Product price trends over time
-- 4. Cross-store price comparison (PricePeek foundation)
--
-- PREREQUISITES: Migration 016 (products catalog) must be run first
-- ============================================

BEGIN;

-- ============================================
-- 1. Add product_id column to record_items
-- ============================================
-- Add column (nullable initially for backfill)
ALTER TABLE record_items 
ADD COLUMN product_id UUID REFERENCES products(id) ON DELETE SET NULL;

-- ============================================
-- 2. Add category_id for direct category access
-- ============================================
-- This is in addition to product.category_id
-- Allows flexibility: item can override product's category if needed
ALTER TABLE record_items
ADD COLUMN category_id UUID REFERENCES categories(id) ON DELETE SET NULL;

-- ============================================
-- 3. Add indexes for performance
-- ============================================
CREATE INDEX record_items_product_id_idx ON record_items(product_id);
CREATE INDEX record_items_category_id_idx ON record_items(category_id);

-- Composite indexes for common queries
CREATE INDEX record_items_user_product_idx ON record_items(user_id, product_id);
CREATE INDEX record_items_product_date_idx ON record_items(product_id, created_at DESC);
CREATE INDEX record_items_user_category_idx ON record_items(user_id, category_id);

-- ============================================
-- 4. Add comments
-- ============================================
COMMENT ON COLUMN record_items.product_id IS 'Foreign key to products table for normalized product aggregation';
COMMENT ON COLUMN record_items.category_id IS 'Direct category link (can override product.category_id if needed)';

-- ============================================
-- 5. Create helper view for easy querying
-- ============================================
CREATE OR REPLACE VIEW record_items_enriched AS
SELECT 
  ri.id,
  ri.receipt_id,
  ri.user_id,
  
  -- Product info
  ri.product_name as raw_product_name,
  p.normalized_name as product_normalized_name,
  p.size as product_size,
  p.unit_type as product_unit_type,
  
  -- Category hierarchy
  c1.name as category_l1,
  c2.name as category_l2,
  c3.name as category_l3,
  COALESCE(ri.category_id, p.category_id) as category_id,
  
  -- Pricing
  ri.quantity,
  ri.unit,
  ri.unit_price,
  ri.line_total,
  ri.on_sale,
  ri.discount_amount,
  
  -- Store info (from record_summaries)
  rs.store_chain_id,
  rs.store_location_id,
  sc.name as store_chain_name,
  sl.name as store_location_name,
  
  -- Receipt info
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

COMMENT ON VIEW record_items_enriched IS 'Enriched view of record_items with product, category, and store information';

-- ============================================
-- 6. Verification
-- ============================================
DO $$
DECLARE
  items_count INTEGER;
  items_with_product INTEGER;
BEGIN
  SELECT COUNT(*) INTO items_count FROM record_items;
  SELECT COUNT(*) INTO items_with_product FROM record_items WHERE product_id IS NOT NULL;
  
  RAISE NOTICE 'Migration 017 completed successfully.';
  RAISE NOTICE 'Total record_items: %', items_count;
  RAISE NOTICE 'Items with product_id: % (backfill needed)', items_with_product;
  RAISE NOTICE '';
  RAISE NOTICE 'Next steps:';
  RAISE NOTICE '1. Implement product normalization logic in backend';
  RAISE NOTICE '2. Backfill existing record_items with product_id';
  RAISE NOTICE '3. Make product_id NOT NULL after backfill';
END $$;

COMMIT;

-- ============================================
-- Future: Make product_id required (after backfill)
-- ============================================
-- Once all record_items have product_id, run:
-- ALTER TABLE record_items ALTER COLUMN product_id SET NOT NULL;
