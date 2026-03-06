-- ============================================
-- Migration 012: record_summaries + record_items（最终形态）
--
-- 已合并以下迁移（新库直接建到最终形态，无需再单独运行）：
--   024_simplify_receipt_items.sql          → 删除 brand/category_l*/ocr_* 列；所有金额改为整型（分）
--   031_record_summaries_information_and_int_totals.sql → record_summaries 金额整型、information JSONB、删 uploaded_at
--   051_category_source_and_user_categories.sql (部分) → record_items.category_source
--   052_user_item_idk.sql                   → record_items.user_marked_idk
--   053_record_items_user_feedback.sql      → record_items.user_feedback
--
-- 注意：record_items 的 product_id / category_id FK 需等 015（categories）和 016（products）
-- 建好后，在 017_link_receipt_items_to_products.sql 里添加。
-- ============================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 1. record_summaries（最终形态）
--    - 金额全部为整型（分），来自 031
--    - information JSONB，来自 031
--    - 无 uploaded_at（031 已删）
-- ============================================
CREATE TABLE IF NOT EXISTS record_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id UUID NOT NULL REFERENCES receipt_status(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  store_chain_id UUID REFERENCES store_chains(id),
  store_location_id UUID REFERENCES store_locations(id),
  store_name TEXT,
  store_address TEXT,

  -- 金额：整型（分）
  subtotal INTEGER,
  tax INTEGER,
  fees INTEGER DEFAULT 0,
  total INTEGER NOT NULL,
  currency TEXT DEFAULT 'USD',

  payment_method TEXT,
  payment_last4 TEXT,

  -- 结构化附加信息（cashier、membership_card、merchant_phone、purchase_time 等）
  information JSONB,

  user_note TEXT,
  user_tags TEXT[],

  receipt_date DATE NOT NULL,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  CONSTRAINT record_summaries_receipt_id_unique UNIQUE(receipt_id)
);

CREATE INDEX IF NOT EXISTS record_summaries_user_id_idx ON record_summaries(user_id);
CREATE INDEX IF NOT EXISTS record_summaries_receipt_date_idx ON record_summaries(receipt_date DESC);
CREATE INDEX IF NOT EXISTS record_summaries_store_chain_idx ON record_summaries(store_chain_id) WHERE store_chain_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS record_summaries_store_location_idx ON record_summaries(store_location_id) WHERE store_location_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS record_summaries_created_at_idx ON record_summaries(created_at DESC);
CREATE INDEX IF NOT EXISTS record_summaries_user_date_idx ON record_summaries(user_id, receipt_date DESC);

CREATE TRIGGER record_summaries_updated_at
  BEFORE UPDATE ON record_summaries
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE record_summaries IS 'Denormalized receipt-level summary data for efficient querying';
COMMENT ON COLUMN record_summaries.subtotal IS 'Subtotal in cents (integer)';
COMMENT ON COLUMN record_summaries.tax IS 'Tax in cents (integer)';
COMMENT ON COLUMN record_summaries.fees IS 'Fees in cents (integer)';
COMMENT ON COLUMN record_summaries.total IS 'Total in cents (integer)';
COMMENT ON COLUMN record_summaries.information IS 'Standardized payload: other_info (cashier, membership_card, merchant_phone, purchase_time) + items (section 2).';

-- ============================================
-- 2. record_items（最终形态）
--    - 无 brand、category_l1/2/3、ocr_coordinates、ocr_confidence（024 已删）
--    - 所有金额/数量为整型（分 × 100），来自 024
--    - product_id / category_id 在 017 里加（需要 015/016 先存在）
--    - category_source，来自 051
--    - user_marked_idk，来自 052
--    - user_feedback，来自 053
-- ============================================
CREATE TABLE IF NOT EXISTS record_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id UUID NOT NULL REFERENCES receipt_status(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

  product_name TEXT NOT NULL,
  product_name_clean TEXT,

  -- quantity: 原值 × 100（如 1.5 → 150）
  quantity BIGINT,
  unit TEXT,
  -- unit_price / line_total / original_price / discount_amount: 分（整型）
  unit_price BIGINT,
  line_total BIGINT NOT NULL,
  on_sale BOOLEAN DEFAULT FALSE,
  original_price BIGINT,
  discount_amount BIGINT,

  item_index INT,

  -- 来自 051
  category_source TEXT,

  -- 来自 052
  user_marked_idk BOOLEAN NOT NULL DEFAULT FALSE,

  -- 来自 053（JSON: {dismissed, reason, comment, dismissed_at}）
  user_feedback JSONB,

  created_at TIMESTAMPTZ DEFAULT NOW(),

  CHECK (quantity IS NULL OR quantity >= 0),
  CHECK (unit_price IS NULL OR unit_price >= 0),
  CHECK (line_total >= 0),
  CHECK (category_source IS NULL OR category_source IN (
    'rule_exact', 'rule_fuzzy', 'llm', 'user_override', 'crowd_assigned'
  ))
);

CREATE INDEX IF NOT EXISTS record_items_receipt_id_idx ON record_items(receipt_id);
CREATE INDEX IF NOT EXISTS record_items_user_id_idx ON record_items(user_id);
CREATE INDEX IF NOT EXISTS record_items_product_name_idx ON record_items(product_name);
CREATE INDEX IF NOT EXISTS record_items_on_sale_idx ON record_items(on_sale) WHERE on_sale = TRUE;
CREATE INDEX IF NOT EXISTS record_items_created_at_idx ON record_items(created_at DESC);
CREATE INDEX IF NOT EXISTS record_items_user_created_idx ON record_items(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS record_items_product_name_trgm_idx ON record_items USING gin(product_name gin_trgm_ops);

COMMENT ON TABLE record_items IS 'Individual line items from receipts - denormalized for efficient querying';
COMMENT ON COLUMN record_items.quantity IS 'Quantity × 100 (e.g. 1.5 → 150). No decimals.';
COMMENT ON COLUMN record_items.unit_price IS 'Unit price in cents. No decimals.';
COMMENT ON COLUMN record_items.line_total IS 'Line total in cents. No decimals.';
COMMENT ON COLUMN record_items.original_price IS 'Original price before discount, in cents.';
COMMENT ON COLUMN record_items.discount_amount IS 'Discount amount in cents.';
COMMENT ON COLUMN record_items.category_source IS 'How this item got category_id: rule_exact, rule_fuzzy, llm, user_override, crowd_assigned. NULL = unset.';
COMMENT ON COLUMN record_items.user_marked_idk IS 'User clicked "I don''t know" on this item. Cleared when backend assigns category_id.';
COMMENT ON COLUMN record_items.user_feedback IS 'User dismissal feedback: {dismissed, reason: "incorrect_item"|"other", comment, dismissed_at}';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 012 completed: record_summaries + record_items (final schema, includes 024/031/051/052/053)';
END $$;
