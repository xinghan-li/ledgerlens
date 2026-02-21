-- ============================================
-- Migration 034: Fix milk and soup dumplings categorization
-- ============================================
-- Purpose:
-- 1. Milk: Seed rule "fuzzy" fails for long names like "milk lactose free hg lf" (low similarity).
--    Change to "contains" so any product name containing "milk" matches Dairy/Milk.
-- 2. Soup dumplings: Actual product is "soup dumplings pork and ginger"; receipt truncates to
--    "SOUP DUMPLINGS PORK AND". We store receipt name as-is; matching uses backend PREFIX match
--    (rule normalized_name starts with receipt name). Add one rule with FULL name so prefix match
--    finds it: normalized_name = 'soup dumplings pork and ginger' -> Grocery/Frozen.
-- Run after: 019, 028 (categories path lowercase)
-- ============================================

BEGIN;

-- 1. Milk: change universal fuzzy rule to contains (so "milk lactose free ..." matches)
UPDATE product_categorization_rules r
SET match_type = 'contains',
    similarity_threshold = 0.90
FROM categories c
WHERE r.category_id = c.id
  AND c.path = 'grocery/dairy/milk'
  AND r.normalized_name = 'milk'
  AND r.store_chain_id IS NULL
  AND r.match_type = 'fuzzy';

-- 2. Soup dumplings pork and ginger: full name rule for PREFIX match (receipt = "soup dumplings pork and")
DO $$
DECLARE
  v_cat_id UUID;
  v_exists INT;
BEGIN
  SELECT id INTO v_cat_id FROM categories WHERE path = 'grocery/frozen' AND level = 2 LIMIT 1;
  IF v_cat_id IS NULL THEN
    RAISE NOTICE '034: No grocery/frozen category found, skip soup dumplings rule';
    RETURN;
  END IF;
  SELECT COUNT(*) INTO v_exists FROM product_categorization_rules
   WHERE normalized_name = 'soup dumplings pork and ginger' AND store_chain_id IS NULL AND category_id = v_cat_id;
  IF v_exists = 0 THEN
    INSERT INTO product_categorization_rules (
      normalized_name, store_chain_id, category_id, match_type, similarity_threshold, source, priority
    ) VALUES ('soup dumplings pork and ginger', NULL, v_cat_id, 'exact', 0.90, 'seed', 200);
    RAISE NOTICE '034: Inserted rule soup dumplings pork and ginger -> grocery/frozen (for prefix match)';
  END IF;
END $$;

COMMIT;
