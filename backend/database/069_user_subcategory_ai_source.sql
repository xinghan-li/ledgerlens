-- ============================================
-- Migration 069: AI subcategory suggestion support
--
-- 1. record_items.user_category_source — tracks how user_category_id was assigned
--    NULL        : auto-resolved from system L1 mapping (RPC)
--    'ai_subcategory' : AI suggested a deeper subcategory (L2/L3)
--    'user_override'  : user manually changed
--
-- 2. prompt_library: new entry 'subcategory_classification' (system prompt for subcategory LLM)
-- 3. prompt_binding: bind above to prompt_key='subcategory_classification'
--
-- PREREQUISITES: 051 (user_categories), 064 (user_category_id on record_items)
-- ============================================

BEGIN;

-- ============================================
-- 1. record_items: add user_category_source
-- ============================================
ALTER TABLE record_items
  ADD COLUMN IF NOT EXISTS user_category_source TEXT;

ALTER TABLE record_items
  DROP CONSTRAINT IF EXISTS record_items_user_category_source_check;

ALTER TABLE record_items
  ADD CONSTRAINT record_items_user_category_source_check
    CHECK (user_category_source IS NULL OR user_category_source IN (
      'ai_subcategory', 'user_override'
    ));

COMMENT ON COLUMN record_items.user_category_source IS
  'How user_category_id was last set beyond L1 resolution: ai_subcategory (LLM picked a deeper node), user_override (user manually changed). NULL = auto-resolved from system L1 via RPC.';

-- ============================================
-- 2. prompt_library: subcategory_classification
-- ============================================
INSERT INTO prompt_library (key, content, content_role, category, is_active)
SELECT
  'subcategory_classification',
  E'You are a personal finance receipt categorization assistant.\n\nYou receive a list of purchased items. Each item has already been assigned a top-level (L1) category by the system. Your task is to assign the most appropriate **subcategory** (L2 or deeper) from the user''s own custom category tree.\n\nCritical rules:\n1. ONLY use subcategory IDs that exist in the user-provided tree. NEVER invent or suggest categories not in the tree.\n2. A subcategory MUST be a descendant of the item''s already-assigned L1 category. Do NOT assign a subcategory that belongs to a different L1.\n3. Be conservative — only assign when confidence is HIGH. A wrong subcategory is worse than leaving it blank. Prefer null over a guess.\n4. If an item''s L1 has no subcategory options listed, always return null.\n5. Items with vague or ambiguous product names that could belong to multiple subcategories should return null.\n\nOutput valid JSON with exactly this schema:\n{\n  "items": [\n    {\n      "item_id": "exact UUID from input",\n      "subcategory_id": "UUID of the matching subcategory node, or null",\n      "confidence": "high | low"\n    }\n  ]\n}\n\nOnly return subcategory_id when confidence is "high". For "low" confidence, subcategory_id must be null.',
  'system',
  'categorization',
  TRUE
WHERE NOT EXISTS (
  SELECT 1 FROM prompt_library WHERE key = 'subcategory_classification'
);

-- ============================================
-- 3. prompt_binding: bind subcategory_classification
-- ============================================
INSERT INTO prompt_binding (prompt_key, library_id, scope, chain_id, location_id, priority, is_active)
SELECT
  'subcategory_classification',
  id,
  'default',
  NULL,
  NULL,
  10,
  TRUE
FROM prompt_library
WHERE key = 'subcategory_classification'
  AND is_active = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM prompt_binding pb
    WHERE pb.prompt_key = 'subcategory_classification'
      AND pb.library_id = prompt_library.id
  );

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 069 completed: record_items.user_category_source added + subcategory_classification prompt seeded.';
END $$;
