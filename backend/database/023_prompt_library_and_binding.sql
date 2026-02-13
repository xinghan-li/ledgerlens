-- ============================================
-- Migration 023: Replace tag-based RAG with prompt_library + prompt_binding
-- ============================================
-- Purpose: Simplify prompt system. Old design: tag_matching_rules -> prompt_tags -> prompt_snippets.
-- New design: prompt_library (content) + prompt_binding (routing by scope).
--
-- Before running: Export existing data via temp/export_rag_tables_to_csv.py
-- Output: temp/prompt_tags.csv, temp/prompt_snippets.csv, temp/tag_matching_rules.csv
-- ============================================

BEGIN;

-- ============================================
-- PART 1: DROP old tables (with field documentation for traceability)
-- ============================================
-- When backend components fail after this migration, search for the table/field name below
-- to understand what the old schema did and how to migrate or fix.
--
-- OLD TABLE: prompt_tags
-- Used by: tag_based_rag.py (detect_tags_from_ocr), prompt_manager.py, extraction_rule_manager.py
-- Purpose: Tag labels for categorizing RAG snippets (e.g. store name, discount pattern).
-- Fields:
--   id              - UUID PK
--   tag_name        - Unique tag identifier. E.g. 't&t', 'deposit_and_fee', 'package_price_discount'.
--                     Used to look up snippets after tag_matching_rules matched.
--   tag_type        - Category: 'store'|'discount_pattern'|'payment_method'|'general'|'validation_rule'.
--                     Affected how store_chain_id was checked (tag_type='store' matched chain normalized_name/aliases).
--   description     - Human description of what the tag is for.
--   priority        - Higher = applied first when combining snippets. Affected sort order in load_rag_snippets.
--   is_active       - Soft delete. False = excluded from queries.
--   created_at      - Timestamp
--   updated_at      - Timestamp
--
-- OLD TABLE: prompt_snippets
-- Used by: tag_based_rag.py (load_rag_snippets, combine_rag_into_prompt)
-- Purpose: Actual RAG content associated with tags. Fetched after tags were detected.
-- Fields:
--   id              - UUID PK
--   tag_id          - FK to prompt_tags. Which tag this snippet belongs to.
--   snippet_type    - 'system_message'|'prompt_addition'|'extraction_rule'|'example'|'validation_rule'.
--                     Determined which bucket the content went into (system_messages, prompt_additions, etc.).
--   content         - The actual text/JSON injected into LLM prompts.
--   priority        - Order within same tag when multiple snippets. Higher = later in combined output.
--   is_active       - Soft delete.
--   created_at      - Timestamp
--   updated_at      - Timestamp
--
-- OLD TABLE: tag_matching_rules
-- Used by: tag_based_rag.py (detect_tags_from_ocr)
-- Purpose: Rules to match tags from OCR raw_text, merchant_name, or store_chain_id.
-- Fields:
--   id              - UUID PK
--   tag_id          - FK to prompt_tags. Which tag to activate when this rule matches.
--   match_type      - 'store_name'|'ocr_pattern'|'regex'|'keyword'|'fuzzy_store_name'.
--                     store_name: merchant_name contains match_pattern (case insensitive)
--                     ocr_pattern: raw_text contains match_pattern
--                     regex: re.search(match_pattern) on raw_text or merchant_name
--                     keyword: substring in raw_text or merchant_name
--                     fuzzy_store_name: rapidfuzz ratio >= 80 with match_pattern
--   match_pattern   - The pattern string (e.g. 't&t', '2/\$', 'Bottle Deposit').
--   match_condition - JSONB. Additional conditions (rarely used).
--   priority        - When multiple rules match, higher priority tag wins for ordering.
--   is_active       - Soft delete.
--   created_at      - Timestamp (no updated_at)
-- ============================================

DROP TABLE IF EXISTS tag_matching_rules CASCADE;
DROP TABLE IF EXISTS prompt_snippets CASCADE;
DROP TABLE IF EXISTS prompt_tags CASCADE;

-- ============================================
-- PART 2: Create new tables
-- ============================================

-- prompt_library: stores actual prompt content
CREATE TABLE prompt_library (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key TEXT NOT NULL,
  category TEXT NOT NULL,
  content_role TEXT NOT NULL CHECK (content_role IN ('system', 'user_template', 'schema')),
  content TEXT NOT NULL,
  version INT DEFAULT 1,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX prompt_library_key_idx ON prompt_library(key);
CREATE INDEX prompt_library_category_idx ON prompt_library(category);
CREATE INDEX prompt_library_active_idx ON prompt_library(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE prompt_library IS 'Prompt content library. Keys: receipt_parse_base, summary_short, anomaly_reasoning, etc.';
COMMENT ON COLUMN prompt_library.key IS 'Unique prompt key, e.g. receipt_parse_base, summary_short';
COMMENT ON COLUMN prompt_library.category IS 'Category: receipt, analysis, marketing, system';
COMMENT ON COLUMN prompt_library.content_role IS 'Role in LLM: system, user_template, schema';
COMMENT ON COLUMN prompt_library.content IS 'Actual prompt text or template';
COMMENT ON COLUMN prompt_library.version IS 'Version for rollout/AB testing';

CREATE TRIGGER prompt_library_updated_at
  BEFORE UPDATE ON prompt_library
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- prompt_binding: routing layer between OCR output and LLM
CREATE TABLE prompt_binding (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prompt_key TEXT NOT NULL,
  library_id UUID NOT NULL REFERENCES prompt_library(id) ON DELETE CASCADE,
  scope TEXT NOT NULL CHECK (scope IN ('default', 'chain', 'location')),
  chain_id UUID NULL,
  location_id UUID NULL,
  priority INT DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CHECK (
    (scope = 'default' AND chain_id IS NULL AND location_id IS NULL) OR
    (scope = 'chain' AND chain_id IS NOT NULL) OR
    (scope = 'location' AND location_id IS NOT NULL)
  )
);

CREATE INDEX prompt_binding_prompt_key_idx ON prompt_binding(prompt_key);
CREATE INDEX prompt_binding_library_id_idx ON prompt_binding(library_id);
CREATE INDEX prompt_binding_scope_idx ON prompt_binding(scope);
CREATE INDEX prompt_binding_chain_id_idx ON prompt_binding(chain_id) WHERE chain_id IS NOT NULL;
CREATE INDEX prompt_binding_location_id_idx ON prompt_binding(location_id) WHERE location_id IS NOT NULL;
CREATE INDEX prompt_binding_active_idx ON prompt_binding(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE prompt_binding IS 'Routing: which library prompt to use for each prompt_key and scope';
COMMENT ON COLUMN prompt_binding.prompt_key IS 'Use case key, e.g. receipt_parse, dashboard_summary';
COMMENT ON COLUMN prompt_binding.library_id IS 'FK to prompt_library';
COMMENT ON COLUMN prompt_binding.scope IS 'default=always; chain=when chain_id matches; location=when location_id matches';
COMMENT ON COLUMN prompt_binding.priority IS 'Higher = applied later (override). Suggested: default=10, chain=50, location=100';

CREATE TRIGGER prompt_binding_updated_at
  BEFORE UPDATE ON prompt_binding
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 023 completed: dropped prompt_tags, prompt_snippets, tag_matching_rules; created prompt_library, prompt_binding';
END $$;
