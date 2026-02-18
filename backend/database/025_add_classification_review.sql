-- ============================================
-- Migration 025: Add classification_review table
-- ============================================
-- Purpose: Admin review queue for receipt items that did not match any category.
-- Rows are auto-inserted when a receipt is processed and items have no category;
-- admin fills normalized_name/category_id and confirms to write to
-- product_categorization_rules and products.
--
-- Run after: 012, 015, 017, 019, 020, 021, 022, 024
-- ============================================

BEGIN;

-- ============================================
-- 1. Create classification_review table
-- ============================================
CREATE TABLE classification_review (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Source (from receipt)
  raw_product_name TEXT NOT NULL,
  source_record_item_id UUID REFERENCES record_items(id) ON DELETE SET NULL,
  store_chain_id UUID REFERENCES store_chains(id) ON DELETE SET NULL,

  -- Admin-filled (required before confirm)
  normalized_name TEXT,
  category_id UUID REFERENCES categories(id) ON DELETE RESTRICT,
  size TEXT,
  unit_type TEXT,
  match_type TEXT NOT NULL DEFAULT 'exact' CHECK (match_type IN ('exact', 'fuzzy', 'contains')),

  -- Status: single field, no is_active
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
    'pending', 'confirmed', 'unable_to_decide', 'deferred', 'cancelled'
  )),

  -- Audit
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  confirmed_at TIMESTAMPTZ,
  confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- ============================================
-- 2. Indexes
-- ============================================
CREATE INDEX classification_review_status_idx ON classification_review(status);
CREATE INDEX classification_review_created_at_idx ON classification_review(created_at DESC);
CREATE INDEX classification_review_raw_store_pending_idx ON classification_review(raw_product_name, store_chain_id)
  WHERE status = 'pending';

-- ============================================
-- 3. Trigger
-- ============================================
CREATE TRIGGER classification_review_updated_at
  BEFORE UPDATE ON classification_review
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- 4. Comments
-- ============================================
COMMENT ON TABLE classification_review IS 'Admin review queue: receipt items with no category match; confirm writes to product_categorization_rules and products';
COMMENT ON COLUMN classification_review.raw_product_name IS 'Original product name from OCR/LLM';
COMMENT ON COLUMN classification_review.normalized_name IS 'Admin-filled; normalized (lowercase, trim, singular) before confirm';
COMMENT ON COLUMN classification_review.category_id IS 'Admin-selected level-3 category; required for confirm';
COMMENT ON COLUMN classification_review.status IS 'pending=to review, confirmed=written, unable_to_decide, deferred, cancelled';
COMMENT ON COLUMN classification_review.source_record_item_id IS 'Trace back to specific record_items row';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 025 completed: classification_review table created';
END $$;
