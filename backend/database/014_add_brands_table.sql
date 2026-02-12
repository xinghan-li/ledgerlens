-- ============================================
-- Migration 014: Add brands table
-- ============================================
-- Purpose: Normalize brand names for consistent brand-level analytics
--
-- Benefits:
-- 1. "How much do I spend on Dole products?"
-- 2. Brand comparison across categories
-- 3. Brand loyalty analysis
-- 4. Prevent brand name typos/variations
--
-- IMPORTANT: Run this BEFORE 016 (products catalog)
-- ============================================

BEGIN;

-- Enable pg_trgm extension for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE brands (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Brand identification
  name TEXT NOT NULL UNIQUE,              -- Display name: 'Dole'
  normalized_name TEXT NOT NULL UNIQUE,   -- 'dole'
  
  -- Alternative names
  aliases TEXT[] DEFAULT '{}',            -- ['DOLE', 'Dole Food Company']
  
  -- Brand info
  description TEXT,
  logo_url TEXT,
  website TEXT,
  
  -- Parent company (for conglomerates)
  parent_company TEXT,
  
  -- Statistics (updated by triggers/jobs)
  product_count INT DEFAULT 0,
  usage_count INT DEFAULT 0,
  
  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX brands_normalized_name_idx ON brands(normalized_name);
CREATE INDEX brands_aliases_idx ON brands USING gin(aliases);
CREATE INDEX brands_usage_count_idx ON brands(usage_count DESC);

-- Text search
CREATE INDEX brands_name_trgm_idx ON brands USING gin(name gin_trgm_ops);

-- Trigger
CREATE TRIGGER brands_updated_at 
  BEFORE UPDATE ON brands
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Comments
COMMENT ON TABLE brands IS 'Normalized brand names for consistent brand-level analytics';
COMMENT ON COLUMN brands.name IS 'Display name of the brand';
COMMENT ON COLUMN brands.normalized_name IS 'Lowercase normalized name for matching';
COMMENT ON COLUMN brands.aliases IS 'Alternative brand names for fuzzy matching';
COMMENT ON COLUMN brands.product_count IS 'Number of products with this brand';
COMMENT ON COLUMN brands.usage_count IS 'Total appearances in receipt_items';

-- ============================================
-- Backfill brands from existing receipt_items (if table exists)
-- ============================================
DO $$
BEGIN
  -- Check if receipt_items table exists
  IF EXISTS (
    SELECT FROM information_schema.tables 
    WHERE table_schema = 'public' 
    AND table_name = 'receipt_items'
  ) THEN
    -- Extract unique brands from receipt_items
    INSERT INTO brands (name, normalized_name)
    SELECT DISTINCT
      INITCAP(TRIM(brand)) as name,
      LOWER(TRIM(brand)) as normalized_name
    FROM receipt_items
    WHERE brand IS NOT NULL 
      AND TRIM(brand) != ''
      AND LENGTH(TRIM(brand)) > 0
    ON CONFLICT (name) DO NOTHING;
    
    RAISE NOTICE 'Backfilled brands from existing receipt_items';
  ELSE
    RAISE NOTICE 'receipt_items table does not exist yet - skipping backfill';
    RAISE NOTICE 'Run migration 012 first, then re-run this migration to backfill brands';
  END IF;
END $$;

-- Verification
DO $$
DECLARE
  brand_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO brand_count FROM brands;
  RAISE NOTICE 'Migration 014 completed successfully.';
  RAISE NOTICE 'Created % brand(s) from existing data', brand_count;
END $$;

COMMIT;

-- ============================================
-- Example queries
-- ============================================
-- List all brands
-- SELECT * FROM brands ORDER BY name;

-- Search for a brand
-- SELECT * FROM brands WHERE normalized_name LIKE '%dole%';

-- Brands with most products (after migration 016)
-- SELECT b.name, b.product_count 
-- FROM brands b 
-- WHERE b.product_count > 0 
-- ORDER BY b.product_count DESC 
-- LIMIT 10;
