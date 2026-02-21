-- ============================================
-- Migration 032: Add phone to store_locations and store_candidates
-- ============================================
-- Purpose: Store canonical phone (xxx-xxx-xxxx) per location so we can use it in
--          information.other_info.merchant_phone instead of relying on OCR.
-- Run after: 031
-- ============================================

BEGIN;

-- 1. store_locations: add phone (canonical format XXX-XXX-XXXX)
ALTER TABLE store_locations
  ADD COLUMN IF NOT EXISTS phone TEXT;

COMMENT ON COLUMN store_locations.phone IS 'Store phone in canonical form xxx-xxx-xxxx (US). Reduces OCR error; use when building information.other_info.merchant_phone.';

-- Optional: constrain to US 10-digit format (uncomment if you only have US stores)
-- ALTER TABLE store_locations ADD CONSTRAINT store_locations_phone_format
--   CHECK (phone IS NULL OR phone ~ '^\d{3}-\d{3}-\d{4}$');

-- 2. store_candidates: add phone for proposed locations
ALTER TABLE store_candidates
  ADD COLUMN IF NOT EXISTS phone TEXT;

COMMENT ON COLUMN store_candidates.phone IS 'Proposed store phone in canonical form xxx-xxx-xxxx. Filled when approving candidate or from OCR.';

COMMIT;

-- ============================================
-- Backfill (run manually or add below with your store IDs)
-- ============================================
-- Example: Trader Joe's Lynnwood (Store #0129) — 19715 Highway 99, Suite 101, Lynnwood WA
-- UPDATE store_locations SET phone = '425-670-0623'
-- WHERE chain_id = (SELECT id FROM store_chains WHERE normalized_name = 'trader_joes' LIMIT 1)
--   AND (address_line1 ILIKE '%19715%' OR address_line1 ILIKE '%Highway 99%')
--   AND city ILIKE '%Lynnwood%';
