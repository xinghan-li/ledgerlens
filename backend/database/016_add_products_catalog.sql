-- ============================================
-- Migration 016: Add products catalog table
-- ============================================
-- Purpose: Create unified product catalog for cross-receipt aggregation
-- and future PricePeek price comparison
--
-- This enables:
-- 1. Aggregate same product across multiple receipts
-- 2. Normalize product names (banana vs BANANA vs Bananas)
-- 3. Cross-store price comparison
-- 4. Efficient product-level analytics
--
-- PREREQUISITES: 
-- - Migration 015 (categories table) must be run first
-- ============================================

BEGIN;

-- Enable pg_trgm extension for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 1. Create products catalog table
-- ============================================
CREATE TABLE products (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Core identification
  normalized_name TEXT NOT NULL,  -- 'banana', 'milk', 'bread' (lowercase, singular)
  
  -- Product specifications
  size TEXT,                      -- '1 lb', '1 gallon', '24 oz'
  unit_type TEXT,                 -- 'lb', 'gallon', 'oz', 'each', 'kg'
  
  -- Classification
  category_id UUID REFERENCES categories(id) ON DELETE SET NULL,
  
  -- Statistics (updated by triggers/jobs)
  usage_count INT DEFAULT 0,      -- How many times this product appears
  last_seen_date DATE,            -- Last time this product was purchased
  
  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Uniqueness constraint
  CONSTRAINT products_unique_key UNIQUE(normalized_name, size)
);

-- ============================================
-- 2. Indexes for performance
-- ============================================
CREATE INDEX products_normalized_name_idx ON products(normalized_name);
CREATE INDEX products_category_idx ON products(category_id) WHERE category_id IS NOT NULL;
CREATE INDEX products_usage_count_idx ON products(usage_count DESC);
CREATE INDEX products_last_seen_idx ON products(last_seen_date DESC NULLS LAST);

-- Text search index
CREATE INDEX products_normalized_name_trgm_idx ON products USING gin(normalized_name gin_trgm_ops);

-- ============================================
-- 3. Triggers
-- ============================================
CREATE TRIGGER products_updated_at 
  BEFORE UPDATE ON products
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- 4. Comments
-- ============================================
COMMENT ON TABLE products IS 'Unified product catalog for cross-receipt aggregation and price comparison';
COMMENT ON COLUMN products.normalized_name IS 'Normalized product name (lowercase, singular) for matching';
COMMENT ON COLUMN products.size IS 'Product size/package (e.g., 1 lb, 1 gallon, 24 oz)';
COMMENT ON COLUMN products.unit_type IS 'Unit of measurement (lb, gallon, oz, each, kg)';
COMMENT ON COLUMN products.usage_count IS 'Number of times this product appears across all receipts';

-- ============================================
-- 5. Verification
-- ============================================
DO $$
BEGIN
  RAISE NOTICE 'Migration 016 completed successfully.';
  RAISE NOTICE 'Created products table with normalized catalog structure';
  RAISE NOTICE 'Next steps:';
  RAISE NOTICE '1. Run migration 017 to link receipt_items to products';
  RAISE NOTICE '2. Implement LLM-based product normalization logic';
  RAISE NOTICE '3. Backfill existing receipt_items with product_id';
END $$;

COMMIT;

-- ============================================
-- Example queries
-- ============================================

-- Create a product
-- INSERT INTO products (normalized_name, size, unit_type, category_id)
-- SELECT 'banana', '1 lb', 'lb', c.id
-- FROM categories c WHERE c.path = 'Grocery/Produce/Fruit';

-- Search for products
-- SELECT p.normalized_name, p.size, c.path as category
-- FROM products p
-- LEFT JOIN categories c ON p.category_id = c.id
-- WHERE p.normalized_name LIKE '%banana%'
-- ORDER BY p.usage_count DESC;

-- Get category hierarchy for a product
-- SELECT 
--   c1.name as l1,
--   c2.name as l2,
--   c3.name as l3,
--   p.normalized_name
-- FROM products p
-- JOIN categories c3 ON p.category_id = c3.id
-- LEFT JOIN categories c2 ON c3.parent_id = c2.id
-- LEFT JOIN categories c1 ON c2.parent_id = c1.id
-- WHERE p.id = 'some-uuid';
