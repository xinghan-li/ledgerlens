-- ============================================
-- Migration 026: Add classification prompt to prompt_library
-- ============================================
-- Purpose: LLM pre-fill for classification_review: suggest category (L1/L2/L3),
--          size, unit_type from raw_product_name and merchant context.
-- Run after: 023, 024, 025
-- ============================================

BEGIN;

-- 1. Insert classification system prompt (only if not exists)
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT
  'classification',
  'classification',
  'system',
  'You are a product categorization expert. You receive a structural receipt with merchant/store context and a list of raw product names (as they appear on the receipt).

Your task: For each raw_product_name, infer the most likely 3-level category (Category I / II / III) based on common merchant rules from Walmart, Costco, Target, and similar retailers. Use the store name and product name to infer category.

Also infer size and unit_type if they appear in the product name (e.g. "Organic Milk 1 Gallon" -> size: "1 gallon", unit_type: "gallon"; "Eggs 12ct" -> size: "12ct", unit_type: "count"). If not clearly present, use null.

Output valid JSON with this schema:
{
  "items": [
    {
      "raw_product_name": "exact string from input",
      "category_i": "Level 1 name (e.g. Grocery)",
      "category_ii": "Level 2 name (e.g. Dairy)",
      "category_iii": "Level 3 name (e.g. Milk)",
      "size": "string or null",
      "unit_type": "string or null"
    }
  ]
}

Category names must match common retail taxonomies: Grocery (Produce, Dairy, Meat & Seafood, Bakery, Frozen, Pantry, Beverages, Snacks, Deli), Household (Cleaning, Paper Products, Kitchen, Storage), Personal Care, Pet Supplies, Health, Other. Use the most specific level 3 that fits.',
  1,
  TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'classification');

-- 2. Create prompt_binding for classification (link to library by key)
INSERT INTO prompt_binding (prompt_key, library_id, scope, chain_id, location_id, priority, is_active)
SELECT
  'classification',
  id,
  'default',
  NULL,
  NULL,
  10,
  TRUE
FROM prompt_library
WHERE key = 'classification' AND is_active = TRUE
  AND NOT EXISTS (SELECT 1 FROM prompt_binding WHERE prompt_key = 'classification' AND scope = 'default');

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 026 completed: classification prompt added';
END $$;
