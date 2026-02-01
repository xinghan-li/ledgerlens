-- ============================================
-- 009_tag_based_rag_system.sql
-- Tag-based RAG system migration
-- ============================================

BEGIN;

-- ============================================
-- 1. Create new tables for tag-based RAG
-- ============================================

-- prompt_tags table: Define tags (e.g., 't&t', 'package_price_discount', 'membership_card')
CREATE TABLE IF NOT EXISTS prompt_tags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tag_name TEXT NOT NULL UNIQUE,
  tag_type TEXT NOT NULL,  -- 'store', 'discount_pattern', 'payment_method', 'general', 'validation_rule'
  description TEXT,
  priority INT DEFAULT 0,  -- Higher priority tags are applied first
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  CHECK (tag_type IN ('store', 'discount_pattern', 'payment_method', 'general', 'validation_rule'))
);

CREATE INDEX prompt_tags_tag_type_idx ON prompt_tags(tag_type);
CREATE INDEX prompt_tags_active_idx ON prompt_tags(is_active) WHERE is_active = TRUE;
CREATE INDEX prompt_tags_priority_idx ON prompt_tags(priority DESC);

COMMENT ON TABLE prompt_tags IS 'Tags for categorizing RAG snippets (e.g., store names, discount patterns)';
COMMENT ON COLUMN prompt_tags.tag_name IS 'Unique tag identifier (e.g., "t&t", "package_price_discount")';
COMMENT ON COLUMN prompt_tags.tag_type IS 'Type of tag: store, discount_pattern, payment_method, general, validation_rule';
COMMENT ON COLUMN prompt_tags.priority IS 'Priority for tag matching (higher = more important)';

-- prompt_snippets table: Store actual RAG content
CREATE TABLE IF NOT EXISTS prompt_snippets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tag_id UUID NOT NULL REFERENCES prompt_tags(id) ON DELETE CASCADE,
  snippet_type TEXT NOT NULL,  -- 'system_message', 'prompt_addition', 'extraction_rule', 'example', 'validation_rule'
  content TEXT NOT NULL,  -- Actual RAG content
  priority INT DEFAULT 0,  -- Priority within the same tag
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  CHECK (snippet_type IN ('system_message', 'prompt_addition', 'extraction_rule', 'example', 'validation_rule'))
);

CREATE INDEX prompt_snippets_tag_id_idx ON prompt_snippets(tag_id);
CREATE INDEX prompt_snippets_type_idx ON prompt_snippets(snippet_type);
CREATE INDEX prompt_snippets_active_idx ON prompt_snippets(is_active) WHERE is_active = TRUE;
CREATE INDEX prompt_snippets_priority_idx ON prompt_snippets(priority DESC);

COMMENT ON TABLE prompt_snippets IS 'RAG snippets associated with tags';
COMMENT ON COLUMN prompt_snippets.snippet_type IS 'Type of snippet: system_message, prompt_addition, extraction_rule, example, validation_rule';
COMMENT ON COLUMN prompt_snippets.content IS 'Actual RAG content to be injected into prompts';

-- tag_matching_rules table: Define how to match tags from OCR/text
CREATE TABLE IF NOT EXISTS tag_matching_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tag_id UUID NOT NULL REFERENCES prompt_tags(id) ON DELETE CASCADE,
  match_type TEXT NOT NULL,  -- 'store_name', 'ocr_pattern', 'regex', 'keyword', 'fuzzy_store_name'
  match_pattern TEXT NOT NULL,  -- Pattern to match (e.g., 't&t', '2/\$', '会员卡')
  match_condition JSONB,  -- Additional matching conditions (e.g., case sensitivity, context)
  priority INT DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  
  CHECK (match_type IN ('store_name', 'ocr_pattern', 'regex', 'keyword', 'fuzzy_store_name'))
);

CREATE INDEX tag_matching_rules_tag_id_idx ON tag_matching_rules(tag_id);
CREATE INDEX tag_matching_rules_type_idx ON tag_matching_rules(match_type);
CREATE INDEX tag_matching_rules_active_idx ON tag_matching_rules(is_active) WHERE is_active = TRUE;
CREATE INDEX tag_matching_rules_pattern_idx ON tag_matching_rules(match_pattern);

COMMENT ON TABLE tag_matching_rules IS 'Rules for matching tags from OCR text or merchant names';
COMMENT ON COLUMN tag_matching_rules.match_type IS 'How to match: store_name (exact), ocr_pattern (simple pattern), regex, keyword, fuzzy_store_name';
COMMENT ON COLUMN tag_matching_rules.match_pattern IS 'Pattern to match against (e.g., "t&t", "2/\$", "会员卡")';

-- ============================================
-- 2. Data Insertion Notes
-- ============================================
-- NOTE: All data insertion operations (tags, snippets, matching rules) have been moved to:
-- - backend/database/2026-01-31_MIGRATION_NOTES.md (detailed descriptions)
-- - backend/scripts/init_deposit_fee_rag.py (initialization script)
-- 
-- Use the RAG Management API (/api/rag/*) or initialization scripts to populate data.
-- See 2026-01-31_MIGRATION_NOTES.md for complete data insertion specifications.

-- ============================================
-- 5. Create updated_at trigger function (if not exists)
-- ============================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add triggers for updated_at
CREATE TRIGGER prompt_tags_updated_at 
  BEFORE UPDATE ON prompt_tags
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER prompt_snippets_updated_at 
  BEFORE UPDATE ON prompt_snippets
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMIT;

-- ============================================
-- Verification queries (run separately to verify)
-- ============================================

-- SELECT * FROM prompt_tags ORDER BY priority DESC;
-- SELECT ps.*, pt.tag_name FROM prompt_snippets ps JOIN prompt_tags pt ON ps.tag_id = pt.id ORDER BY pt.priority DESC, ps.priority DESC;
-- SELECT tmr.*, pt.tag_name FROM tag_matching_rules tmr JOIN prompt_tags pt ON tmr.tag_id = pt.id ORDER BY pt.priority DESC, tmr.priority DESC;
