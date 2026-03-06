-- ============================================
-- Migration 025: classification_review 表（最终形态）
--
-- 已合并以下迁移（新库直接建到最终形态，无需再单独运行）：
--   027_size_quantity_unit_package.sql (classification_review 部分)
--     → size/unit_type 列改为 size_quantity/size_unit/package_type
--
-- PREREQUISITES: 012, 015, 017（record_items + categories）
-- ============================================

BEGIN;

CREATE TABLE classification_review (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  raw_product_name TEXT NOT NULL,
  source_record_item_id UUID REFERENCES record_items(id) ON DELETE SET NULL,
  store_chain_id UUID REFERENCES store_chains(id) ON DELETE SET NULL,

  -- Admin-filled（来自 027 的最终列结构）
  normalized_name TEXT,
  category_id UUID REFERENCES categories(id) ON DELETE RESTRICT,
  size_quantity NUMERIC(12,2),
  size_unit TEXT,
  package_type TEXT,
  match_type TEXT NOT NULL DEFAULT 'exact' CHECK (match_type IN ('exact', 'fuzzy', 'contains')),

  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
    'pending', 'confirmed', 'unable_to_decide', 'deferred', 'cancelled'
  )),

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  confirmed_at TIMESTAMPTZ,
  confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX classification_review_status_idx ON classification_review(status);
CREATE INDEX classification_review_created_at_idx ON classification_review(created_at DESC);
CREATE INDEX classification_review_raw_store_pending_idx ON classification_review(raw_product_name, store_chain_id)
  WHERE status = 'pending';

CREATE TRIGGER classification_review_updated_at
  BEFORE UPDATE ON classification_review
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE classification_review IS 'Admin review queue: receipt items with no category match; confirm writes to product_categorization_rules and products';
COMMENT ON COLUMN classification_review.raw_product_name IS 'Original product name from OCR/LLM';
COMMENT ON COLUMN classification_review.normalized_name IS 'Admin-filled; normalized (lowercase, trim) before confirm';
COMMENT ON COLUMN classification_review.size_quantity IS 'Numeric quantity, 2 decimal places (e.g. 3.50)';
COMMENT ON COLUMN classification_review.size_unit IS 'Unit of measure (oz, ml, lb, ct, etc.)';
COMMENT ON COLUMN classification_review.package_type IS 'Package type (bottle, box, bag, etc.)';
COMMENT ON COLUMN classification_review.status IS 'pending=to review, confirmed=written, unable_to_decide, deferred, cancelled';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 025 completed: classification_review (final schema, incl. 027 column structure)';
END $$;
