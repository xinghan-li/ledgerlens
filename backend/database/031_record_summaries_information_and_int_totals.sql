-- Migration 031: record_summaries – information JSON, totals as int (cents), drop uploaded_at
--
-- 1. Add information JSONB: standardized payload (section2 items + section1/4 extras).
--    See backend/database/documents/record_summaries_information_json_proposal.md
-- 2. store_address: application layer will fill from store_locations when store_location_id set.
-- 3. subtotal, tax, fees, total → integer (cents).
-- 4. Drop uploaded_at (redundant with receipt_status.uploaded_at).

BEGIN;

-- Add information column (nullable for existing rows)
ALTER TABLE record_summaries
  ADD COLUMN IF NOT EXISTS information JSONB;

COMMENT ON COLUMN record_summaries.information IS
  'Standardized payload: other_info (cashier, membership_card, merchant_phone, purchase_time) + items (section 2). Excludes fields already in this row.';

-- Migrate existing numeric totals to integer cents, then change type
-- Step: add new columns, backfill, drop old, rename (to avoid long lock)
ALTER TABLE record_summaries ADD COLUMN IF NOT EXISTS subtotal_cents INTEGER;
ALTER TABLE record_summaries ADD COLUMN IF NOT EXISTS tax_cents INTEGER;
ALTER TABLE record_summaries ADD COLUMN IF NOT EXISTS fees_cents INTEGER;
ALTER TABLE record_summaries ADD COLUMN IF NOT EXISTS total_cents INTEGER;

UPDATE record_summaries
SET
  subtotal_cents = CASE WHEN subtotal IS NOT NULL THEN ROUND(subtotal * 100)::INTEGER ELSE NULL END,
  tax_cents      = CASE WHEN tax IS NOT NULL THEN ROUND(tax * 100)::INTEGER ELSE NULL END,
  fees_cents     = CASE WHEN fees IS NOT NULL THEN ROUND(fees * 100)::INTEGER ELSE 0 END,
  total_cents    = ROUND(total * 100)::INTEGER
WHERE total IS NOT NULL;

UPDATE record_summaries SET total_cents = ROUND(total * 100)::INTEGER WHERE total IS NOT NULL AND total_cents IS NULL;

ALTER TABLE record_summaries DROP COLUMN IF EXISTS subtotal;
ALTER TABLE record_summaries DROP COLUMN IF EXISTS tax;
ALTER TABLE record_summaries DROP COLUMN IF EXISTS fees;
ALTER TABLE record_summaries DROP COLUMN IF EXISTS total;

ALTER TABLE record_summaries RENAME COLUMN subtotal_cents TO subtotal;
ALTER TABLE record_summaries RENAME COLUMN tax_cents TO tax;
ALTER TABLE record_summaries RENAME COLUMN fees_cents TO fees;
ALTER TABLE record_summaries RENAME COLUMN total_cents TO total;

ALTER TABLE record_summaries ALTER COLUMN total SET NOT NULL;

COMMENT ON COLUMN record_summaries.subtotal IS 'Subtotal in cents (integer)';
COMMENT ON COLUMN record_summaries.tax IS 'Tax in cents (integer)';
COMMENT ON COLUMN record_summaries.fees IS 'Fees in cents (integer)';
COMMENT ON COLUMN record_summaries.total IS 'Total in cents (integer)';

-- Drop uploaded_at
ALTER TABLE record_summaries DROP COLUMN IF EXISTS uploaded_at;

COMMIT;
