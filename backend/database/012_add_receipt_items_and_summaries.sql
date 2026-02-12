-- ============================================
-- Migration 012: Add receipt_items and receipt_summaries tables
-- ============================================
-- Purpose: Extract structured data from receipt_processing_runs.output_payload
-- into dedicated tables for efficient querying and aggregation.
--
-- This enables:
-- 1. User to query/analyze their spending by item, category, store
-- 2. Export API for external price aggregation apps (GasBuddy-like)
-- 3. Efficient cross-receipt item/price analysis
--
-- Note: receipt_processing_runs.output_payload remains as the source of truth.
-- These tables are derived/denormalized for performance.
-- ============================================

BEGIN;

-- Enable pg_trgm extension for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 1. receipt_summaries - Receipt-level metadata
-- ============================================
CREATE TABLE IF NOT EXISTS receipt_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  
  -- Store information
  store_chain_id UUID REFERENCES store_chains(id),
  store_location_id UUID REFERENCES store_locations(id),
  store_name TEXT, -- Store name from OCR/LLM (if not matched to store_chains)
  store_address TEXT, -- Store address from OCR
  
  -- Financial totals
  subtotal NUMERIC(10, 2),
  tax NUMERIC(10, 2),
  fees NUMERIC(10, 2) DEFAULT 0,
  total NUMERIC(10, 2) NOT NULL,
  currency TEXT DEFAULT 'USD',
  
  -- Payment information
  payment_method TEXT, -- 'credit_card', 'debit', 'cash', 'membership', etc.
  payment_last4 TEXT, -- Last 4 digits of card (if available)
  
  -- User annotations
  user_note TEXT,
  user_tags TEXT[], -- e.g., ['business', 'grocery', 'monthly']
  
  -- Dates
  receipt_date DATE NOT NULL, -- Date on the receipt
  uploaded_at TIMESTAMPTZ, -- When user uploaded (redundant with receipts table)
  
  -- Metadata
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Constraints
  CONSTRAINT receipt_summaries_receipt_id_unique UNIQUE(receipt_id)
);

-- Indexes for receipt_summaries
CREATE INDEX IF NOT EXISTS receipt_summaries_user_id_idx ON receipt_summaries(user_id);
CREATE INDEX IF NOT EXISTS receipt_summaries_receipt_date_idx ON receipt_summaries(receipt_date DESC);
CREATE INDEX IF NOT EXISTS receipt_summaries_store_chain_idx ON receipt_summaries(store_chain_id) WHERE store_chain_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS receipt_summaries_store_location_idx ON receipt_summaries(store_location_id) WHERE store_location_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS receipt_summaries_created_at_idx ON receipt_summaries(created_at DESC);
CREATE INDEX IF NOT EXISTS receipt_summaries_user_date_idx ON receipt_summaries(user_id, receipt_date DESC);

-- Comments
COMMENT ON TABLE receipt_summaries IS 'Denormalized receipt-level summary data for efficient querying and export';
COMMENT ON COLUMN receipt_summaries.receipt_id IS 'Foreign key to receipts table (one-to-one)';
COMMENT ON COLUMN receipt_summaries.store_name IS 'Store name from OCR if not matched to store_chains';
COMMENT ON COLUMN receipt_summaries.receipt_date IS 'Date on the receipt (may differ from uploaded_at)';
COMMENT ON COLUMN receipt_summaries.user_tags IS 'User-defined tags for categorization';

-- ============================================
-- 2. receipt_items - Individual line items
-- ============================================
CREATE TABLE IF NOT EXISTS receipt_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  
  -- Product information (from OCR/LLM)
  product_name TEXT NOT NULL, -- Raw product name from OCR/LLM
  product_name_clean TEXT, -- Cleaned/normalized version (optional)
  brand TEXT, -- Brand name if extracted
  
  -- Pricing
  quantity NUMERIC(10, 3), -- Support fractional quantities (e.g., 1.27 lb)
  unit TEXT, -- 'lb', 'kg', 'gallon', 'pack', 'each', 'oz', etc.
  unit_price NUMERIC(10, 2), -- Price per unit
  line_total NUMERIC(10, 2) NOT NULL, -- Total for this line item
  
  -- Discount information
  on_sale BOOLEAN DEFAULT FALSE,
  original_price NUMERIC(10, 2), -- Original price before discount
  discount_amount NUMERIC(10, 2), -- Discount amount if on sale
  
  -- User categorization (can be set by user or LLM)
  category_l1 TEXT, -- Level 1: e.g., 'Grocery', 'Household', 'Personal Care'
  category_l2 TEXT, -- Level 2: e.g., 'Dairy', 'Cleaning', 'Health'
  category_l3 TEXT, -- Level 3: e.g., 'Milk', 'Detergent', 'Vitamins'
  
  -- OCR metadata (for debugging/verification)
  ocr_coordinates JSONB, -- Original OCR bounding box coordinates
  ocr_confidence NUMERIC(3, 2), -- OCR confidence score (0.00 - 1.00)
  
  -- Item sequence (order in the receipt)
  item_index INT, -- Position in the receipt (0-based)
  
  -- Metadata
  created_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Constraints
  CHECK (quantity IS NULL OR quantity >= 0),
  CHECK (unit_price IS NULL OR unit_price >= 0),
  CHECK (line_total >= 0),
  CHECK (ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1))
);

-- Indexes for receipt_items
CREATE INDEX IF NOT EXISTS receipt_items_receipt_id_idx ON receipt_items(receipt_id);
CREATE INDEX IF NOT EXISTS receipt_items_user_id_idx ON receipt_items(user_id);
CREATE INDEX IF NOT EXISTS receipt_items_product_name_idx ON receipt_items(product_name);
CREATE INDEX IF NOT EXISTS receipt_items_category_l1_idx ON receipt_items(category_l1) WHERE category_l1 IS NOT NULL;
CREATE INDEX IF NOT EXISTS receipt_items_category_l2_idx ON receipt_items(category_l2) WHERE category_l2 IS NOT NULL;
CREATE INDEX IF NOT EXISTS receipt_items_category_l3_idx ON receipt_items(category_l3) WHERE category_l3 IS NOT NULL;
CREATE INDEX IF NOT EXISTS receipt_items_on_sale_idx ON receipt_items(on_sale) WHERE on_sale = TRUE;
CREATE INDEX IF NOT EXISTS receipt_items_created_at_idx ON receipt_items(created_at DESC);
CREATE INDEX IF NOT EXISTS receipt_items_user_created_idx ON receipt_items(user_id, created_at DESC);

-- Indexes for text search (product name)
CREATE INDEX IF NOT EXISTS receipt_items_product_name_trgm_idx ON receipt_items USING gin(product_name gin_trgm_ops);

-- Comments
COMMENT ON TABLE receipt_items IS 'Individual line items from receipts - denormalized for efficient querying';
COMMENT ON COLUMN receipt_items.product_name IS 'Raw product name from OCR/LLM output';
COMMENT ON COLUMN receipt_items.product_name_clean IS 'Cleaned/normalized product name (optional)';
COMMENT ON COLUMN receipt_items.quantity IS 'Quantity purchased (supports fractional for weight-based items)';
COMMENT ON COLUMN receipt_items.unit IS 'Unit of measurement (lb, kg, gallon, pack, each, etc.)';
COMMENT ON COLUMN receipt_items.category_l1 IS 'Level 1 category (Grocery, Household, Personal Care, etc.)';
COMMENT ON COLUMN receipt_items.category_l2 IS 'Level 2 category (Dairy, Cleaning, Health, etc.)';
COMMENT ON COLUMN receipt_items.category_l3 IS 'Level 3 category (Milk, Detergent, Vitamins, etc.)';
COMMENT ON COLUMN receipt_items.ocr_coordinates IS 'Original OCR bounding box for verification';
COMMENT ON COLUMN receipt_items.item_index IS 'Position in the receipt (0-based)';

-- ============================================
-- 3. Enable pg_trgm extension for fuzzy text search
-- ============================================
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================
-- 4. Add trigger for updated_at on receipt_summaries
-- ============================================
CREATE TRIGGER receipt_summaries_updated_at 
  BEFORE UPDATE ON receipt_summaries
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- 5. Verification queries
-- ============================================
DO $$
BEGIN
    RAISE NOTICE 'Migration 012 completed successfully.';
    RAISE NOTICE 'Created tables: receipt_summaries, receipt_items';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Update receipt processing workflow to populate these tables';
    RAISE NOTICE '2. Backfill existing receipts from receipt_processing_runs.output_payload';
    RAISE NOTICE '3. Create export API endpoint for external apps';
END $$;

COMMIT;

-- ============================================
-- Example queries for validation
-- ============================================

-- Check if tables were created
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('receipt_summaries', 'receipt_items');

-- Check indexes
-- SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename IN ('receipt_summaries', 'receipt_items');

-- ============================================
-- Future enhancements (not in this migration)
-- ============================================
-- 1. Add materialized views for common aggregations (monthly spending by category)
-- 2. Add partitioning by date for receipt_items (when > 10M rows)
-- 3. Add full-text search indexes for product names
-- 4. Add product_id foreign key when products table is created
-- ============================================
