-- ============================================
-- Migration 033: Ensure find_categorization_rule has no prefix logic
-- ============================================
-- Purpose: Prefix match (receipt truncated, rule has full name) is implemented
-- in the backend (receipt_categorizer). This migration ensures the DB function
-- only does exact → fuzzy → contains. If prefix was ever added to the function
-- in the DB, this reverts it to the canonical version.
-- ============================================

BEGIN;

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
  -- Strategy: Try store-specific rules first, then universal rules (exact → fuzzy → contains only).
  -- Prefix match (receipt name truncated) is done in backend, not in DB.

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
  
  -- 3. Try store-specific fuzzy match
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
  
  -- 4. Try universal fuzzy match
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

COMMENT ON FUNCTION find_categorization_rule IS 'Find best matching categorization rule (exact/fuzzy/contains only). Prefix match for truncated receipt names is done in backend.';

COMMIT;
