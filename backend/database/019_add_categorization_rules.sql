-- ============================================
-- Migration 019: Add product categorization rules table
-- ============================================
-- Purpose: Store learned categorization rules for automatic product classification
--
-- This enables:
-- 1. Learning from user corrections (manual rules)
-- 2. Fuzzy matching for similar product names
-- 3. Priority-based rule application
-- 4. Rule statistics and optimization
--
-- PREREQUISITES: Migration 015 (categories tree) must be run first
-- ============================================

BEGIN;

-- ============================================
-- 1. Create categorization rules table
-- ============================================
CREATE TABLE product_categorization_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Matching pattern
  normalized_name TEXT NOT NULL,           -- Normalized product name (e.g., "banana")
  original_examples TEXT[],                -- Example original names (e.g., ["BANANA", "Dole Banana"])
  
  -- Store-specific (optional)
  store_chain_id UUID REFERENCES store_chains(id) ON DELETE CASCADE,
  -- NULL = universal rule (applies to all stores)
  -- Non-NULL = store-specific rule (only applies to this store chain)
  
  -- Category mapping
  category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  
  -- Matching configuration
  match_type TEXT DEFAULT 'fuzzy',         -- 'exact', 'fuzzy', 'contains'
  similarity_threshold NUMERIC(3,2) DEFAULT 0.90,  -- Fuzzy match threshold (0.90 = 90%)
  
  -- Metadata
  source TEXT DEFAULT 'manual',            -- 'manual' (user correction), 'auto' (ML), 'seed' (initial)
  priority INT DEFAULT 100,                -- Priority (lower = higher priority)
  times_matched INT DEFAULT 0,             -- Number of times this rule was matched
  last_matched_at TIMESTAMPTZ,             -- Last time this rule was used
  
  -- Audit
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Constraints
  UNIQUE(normalized_name, store_chain_id, category_id),
  CHECK (similarity_threshold >= 0.50 AND similarity_threshold <= 1.00),
  CHECK (priority >= 0),
  CHECK (match_type IN ('exact', 'fuzzy', 'contains'))
);

-- ============================================
-- 2. Add indexes for performance
-- ============================================
CREATE INDEX rules_normalized_name_idx ON product_categorization_rules(normalized_name);
CREATE INDEX rules_store_chain_idx ON product_categorization_rules(store_chain_id) WHERE store_chain_id IS NOT NULL;
CREATE INDEX rules_category_id_idx ON product_categorization_rules(category_id);
CREATE INDEX rules_priority_idx ON product_categorization_rules(priority);
CREATE INDEX rules_source_idx ON product_categorization_rules(source);
CREATE INDEX rules_times_matched_idx ON product_categorization_rules(times_matched DESC);

-- Composite index for store-specific lookup
CREATE INDEX rules_name_store_idx ON product_categorization_rules(normalized_name, store_chain_id);

-- Text similarity index for fuzzy matching
CREATE INDEX rules_normalized_name_trgm_idx ON product_categorization_rules USING gin(normalized_name gin_trgm_ops);

-- ============================================
-- 3. Add trigger for updated_at
-- ============================================
CREATE TRIGGER rules_updated_at 
  BEFORE UPDATE ON product_categorization_rules
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- 4. Add comments
-- ============================================
COMMENT ON TABLE product_categorization_rules IS 'Product categorization rules learned from user corrections and ML';
COMMENT ON COLUMN product_categorization_rules.normalized_name IS 'Normalized product name to match against';
COMMENT ON COLUMN product_categorization_rules.original_examples IS 'Array of original product names this rule was learned from';
COMMENT ON COLUMN product_categorization_rules.category_id IS 'Target category for products matching this rule';
COMMENT ON COLUMN product_categorization_rules.match_type IS 'Matching strategy: exact (=), fuzzy (similarity), contains (LIKE)';
COMMENT ON COLUMN product_categorization_rules.similarity_threshold IS 'Minimum similarity score for fuzzy matching (0.50-1.00)';
COMMENT ON COLUMN product_categorization_rules.source IS 'Rule origin: manual (user), auto (ML), seed (initial data)';
COMMENT ON COLUMN product_categorization_rules.priority IS 'Rule priority (lower number = higher priority)';
COMMENT ON COLUMN product_categorization_rules.times_matched IS 'Number of times this rule was successfully matched';

-- ============================================
-- 5. Create helper functions
-- ============================================

-- Function to find matching rule for a product (store-aware)
CREATE OR REPLACE FUNCTION find_categorization_rule(
  p_normalized_name TEXT,
  p_store_chain_id UUID DEFAULT NULL,
  p_threshold NUMERIC DEFAULT 0.90
)
RETURNS TABLE (
  rule_id UUID,
  category_id UUID,
  match_type TEXT,
  similarity_score NUMERIC,
  is_store_specific BOOLEAN
) AS $$
BEGIN
  -- Strategy: Try store-specific rules first, then universal rules
  
  -- 1. Try store-specific exact match first (highest priority)
  IF p_store_chain_id IS NOT NULL THEN
    RETURN QUERY
    SELECT 
      r.id,
      r.category_id,
      r.match_type,
      1.0::NUMERIC as similarity_score,
      TRUE as is_store_specific
    FROM product_categorization_rules r
    WHERE r.normalized_name = p_normalized_name
      AND r.store_chain_id = p_store_chain_id
      AND r.match_type = 'exact'
    ORDER BY r.priority ASC, r.times_matched DESC
    LIMIT 1;
    
    IF FOUND THEN
      RETURN;
    END IF;
  END IF;
  
  -- 2. Try universal exact match
  RETURN QUERY
  SELECT 
    r.id,
    r.category_id,
    r.match_type,
    1.0::NUMERIC as similarity_score,
    FALSE as is_store_specific
  FROM product_categorization_rules r
  WHERE r.normalized_name = p_normalized_name
    AND r.store_chain_id IS NULL
    AND r.match_type = 'exact'
  ORDER BY r.priority ASC, r.times_matched DESC
  LIMIT 1;
  
  IF FOUND THEN
    RETURN;
  END IF;
  
  -- 3. Try store-specific fuzzy match (similarity() returns real, cast to NUMERIC to match return type)
  IF p_store_chain_id IS NOT NULL THEN
    RETURN QUERY
    SELECT 
      r.id,
      r.category_id,
      r.match_type,
      (similarity(r.normalized_name, p_normalized_name))::NUMERIC as similarity_score,
      TRUE as is_store_specific
    FROM product_categorization_rules r
    WHERE r.store_chain_id = p_store_chain_id
      AND r.match_type = 'fuzzy'
      AND similarity(r.normalized_name, p_normalized_name) >= GREATEST(r.similarity_threshold, p_threshold)
    ORDER BY similarity(r.normalized_name, p_normalized_name) DESC, r.priority ASC, r.times_matched DESC
    LIMIT 1;
    
    IF FOUND THEN
      RETURN;
    END IF;
  END IF;
  
  -- 4. Try universal fuzzy match (similarity() returns real, cast to NUMERIC to match return type)
  RETURN QUERY
  SELECT 
    r.id,
    r.category_id,
    r.match_type,
    (similarity(r.normalized_name, p_normalized_name))::NUMERIC as similarity_score,
    FALSE as is_store_specific
  FROM product_categorization_rules r
  WHERE r.store_chain_id IS NULL
    AND r.match_type = 'fuzzy'
    AND similarity(r.normalized_name, p_normalized_name) >= GREATEST(r.similarity_threshold, p_threshold)
  ORDER BY similarity(r.normalized_name, p_normalized_name) DESC, r.priority ASC, r.times_matched DESC
  LIMIT 1;
  
  IF FOUND THEN
    RETURN;
  END IF;
  
  -- 5. Try store-specific contains match
  IF p_store_chain_id IS NOT NULL THEN
    RETURN QUERY
    SELECT 
      r.id,
      r.category_id,
      r.match_type,
      0.8::NUMERIC as similarity_score,
      TRUE as is_store_specific
    FROM product_categorization_rules r
    WHERE r.store_chain_id = p_store_chain_id
      AND r.match_type = 'contains'
      AND p_normalized_name LIKE '%' || r.normalized_name || '%'
    ORDER BY LENGTH(r.normalized_name) DESC, r.priority ASC, r.times_matched DESC
    LIMIT 1;
    
    IF FOUND THEN
      RETURN;
    END IF;
  END IF;
  
  -- 6. Try universal contains match
  RETURN QUERY
  SELECT 
    r.id,
    r.category_id,
    r.match_type,
    0.8::NUMERIC as similarity_score,
    FALSE as is_store_specific
  FROM product_categorization_rules r
  WHERE r.store_chain_id IS NULL
    AND r.match_type = 'contains'
    AND p_normalized_name LIKE '%' || r.normalized_name || '%'
  ORDER BY LENGTH(r.normalized_name) DESC, r.priority ASC, r.times_matched DESC
  LIMIT 1;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION find_categorization_rule IS 'Find best matching categorization rule for a normalized product name';

-- Function to update rule match statistics
CREATE OR REPLACE FUNCTION update_rule_match_stats(p_rule_id UUID)
RETURNS VOID AS $$
BEGIN
  UPDATE product_categorization_rules
  SET 
    times_matched = times_matched + 1,
    last_matched_at = NOW()
  WHERE id = p_rule_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_rule_match_stats IS 'Increment match count and update timestamp for a rule';

-- ============================================
-- 6. Verification
-- ============================================
DO $$
BEGIN
  RAISE NOTICE 'Migration 019 completed successfully.';
  RAISE NOTICE 'Created table: product_categorization_rules';
  RAISE NOTICE 'Created function: find_categorization_rule()';
  RAISE NOTICE 'Created function: update_rule_match_stats()';
  RAISE NOTICE '';
  RAISE NOTICE 'Next steps:';
  RAISE NOTICE '1. Correct category classifications in standardization_summary.csv';
  RAISE NOTICE '2. Run import_category_rules.py to load corrected rules';
  RAISE NOTICE '3. Re-generate standardization preview to verify rules work';
END $$;

COMMIT;
