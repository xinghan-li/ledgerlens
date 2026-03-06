-- ============================================
-- Migration 019: Add product categorization rules table
--
-- 注意：find_categorization_rule() 函数本文件不再创建。
-- 原因：该函数在 033 中被重写，在 037 中被 DROP——新库从一开始就不需要它，
-- 所有匹配逻辑已移至 Python 后端。
-- 已废弃相关文件：
--   033_ensure_find_categorization_rule_no_prefix_match.sql → deprecated/
--   037_drop_find_categorization_rule_rpc.sql               → deprecated/
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
-- 5. Helper function: update_rule_match_stats
-- NOTE: find_categorization_rule() 不再创建——匹配逻辑由 Python 后端负责。
--       如需参考原始 DB 函数实现，见 deprecated/033_*.sql
-- ============================================
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
  RAISE NOTICE 'Migration 019 completed: product_categorization_rules + update_rule_match_stats (find_categorization_rule NOT created; backend-only matching)';
END $$;

COMMIT;
