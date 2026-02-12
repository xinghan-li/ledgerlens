-- ============================================
-- Migration 011: Simplify receipts current_stage values
-- ⚠️ ONLY RUN IF YOU PREVIOUSLY RAN 008
-- ============================================
-- This migration reverts the granular stage values from 008 back to simpler values
-- to match the current codebase implementation.
--
-- Background:
-- - Migration 008 expanded stage values for better debugging
-- - Current codebase uses simpler stage values
-- - Need to migrate data back and update constraints
--
-- Old values (from 008): 'ocr_google', 'ocr_aws', 'llm_primary', 'llm_fallback',
--                        'sum_check_failed', 'manual_review', 'success', 'failed'
-- New values (current code): 'ocr', 'llm_primary', 'llm_fallback', 'manual'
--
-- ============================================

BEGIN;

-- ============================================
-- Step 1: Check current data distribution (diagnostic)
-- ============================================
SELECT 
    current_stage, 
    COUNT(*) as count
FROM receipts
GROUP BY current_stage
ORDER BY count DESC;

-- ============================================
-- Step 2: Drop old constraint first
-- ============================================
ALTER TABLE receipts DROP CONSTRAINT IF EXISTS receipts_current_stage_check;

-- ============================================
-- Step 3: Migrate existing data to simplified values
-- ============================================
UPDATE receipts 
SET current_stage = CASE 
    -- OCR stages → 'ocr'
    WHEN current_stage IN ('ocr_google', 'ocr_aws') THEN 'ocr'
    
    -- Sum check failed → 'manual' (needs manual review)
    WHEN current_stage = 'sum_check_failed' THEN 'manual'
    
    -- Manual review → 'manual'
    WHEN current_stage = 'manual_review' THEN 'manual'
    
    -- Failed stage → 'ocr' (failed at OCR stage)
    WHEN current_stage = 'failed' THEN 'ocr'
    
    -- Success stage → 'llm_primary' (successfully processed by primary LLM)
    WHEN current_stage = 'success' THEN 'llm_primary'
    
    -- Already using new values → keep as is
    WHEN current_stage IN ('ocr', 'llm_primary', 'llm_fallback', 'manual') THEN current_stage
    
    -- Unknown values → default to 'manual'
    ELSE 'manual'
END
WHERE current_stage NOT IN ('ocr', 'llm_primary', 'llm_fallback', 'manual');

-- ============================================
-- Step 4: Add simplified constraint
-- ============================================
ALTER TABLE receipts ADD CONSTRAINT receipts_current_stage_check
  CHECK (current_stage IN ('ocr', 'llm_primary', 'llm_fallback', 'manual'));

-- ============================================
-- Step 5: Update column comment
-- ============================================
COMMENT ON COLUMN receipts.current_stage IS 
  'Current processing stage: ocr (OCR processing), llm_primary (primary LLM), llm_fallback (fallback LLM), manual (manual review needed)';

-- ============================================
-- Step 6: Verify migration success
-- ============================================
DO $$
DECLARE
    invalid_count INTEGER;
    stage_distribution TEXT;
BEGIN
    -- Check for invalid values
    SELECT COUNT(*) INTO invalid_count
    FROM receipts
    WHERE current_stage NOT IN ('ocr', 'llm_primary', 'llm_fallback', 'manual');
    
    IF invalid_count > 0 THEN
        RAISE EXCEPTION 'Migration failed: % rows have invalid current_stage values', invalid_count;
    END IF;
    
    -- Get distribution for logging
    SELECT string_agg(current_stage || ':' || cnt::text, ', ')
    INTO stage_distribution
    FROM (
        SELECT current_stage, COUNT(*) as cnt 
        FROM receipts 
        GROUP BY current_stage 
        ORDER BY cnt DESC
    ) sub;
    
    RAISE NOTICE 'Migration 011 completed successfully. Stage distribution: %', stage_distribution;
END $$;

COMMIT;

-- ============================================
-- Expected output:
-- ============================================
-- NOTICE: Migration 011 completed successfully. Stage distribution: ocr:X, llm_primary:Y, manual:Z
-- ============================================
