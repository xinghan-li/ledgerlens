-- ============================================
-- Migration 008: Update current_stage to more granular values for better debugging
-- ============================================
-- This migration updates the current_stage column in receipts table to support
-- more granular stage values for better debugging and troubleshooting.
--
-- Old values: 'ocr', 'llm_primary', 'llm_fallback', 'manual'
-- New values: 'ocr_google', 'ocr_aws', 'llm_primary', 'llm_fallback', 
--            'sum_check_failed', 'manual_review', 'success', 'failed'
--
-- This migration is idempotent and can be run multiple times safely.
-- ============================================

BEGIN;

-- Step 1: Drop old constraint FIRST (to allow data updates without constraint violations)
ALTER TABLE receipts DROP CONSTRAINT IF EXISTS receipts_current_stage_check;

-- Step 2: Update all existing data to new values
-- NOTE: Data migration operations have been moved to:
-- - backend/database/2026-01-31_MIGRATION_NOTES.md (Section 4.1)
-- 
-- IMPORTANT: You MUST run the data migration UPDATE statements from the migration notes
-- BEFORE adding the new constraint in Step 3, otherwise the constraint will fail.
-- 
-- The migration notes contain the complete SQL template for:
-- - Mapping 'manual' → 'manual_review'
-- - Mapping 'ocr' → 'ocr_google'
-- - Mapping 'pending' → 'ocr_google'
-- - Handling NULL values based on current_status

-- Step 3: Add new check constraint with more granular stages
ALTER TABLE receipts ADD CONSTRAINT receipts_current_stage_check
  CHECK (current_stage IN (
    'ocr_google',        -- Google OCR processing
    'ocr_aws',           -- AWS OCR processing (fallback)
    'llm_primary',       -- Primary LLM processing (Gemini or OpenAI)
    'llm_fallback',      -- Backup LLM processing (AWS OCR + GPT)
    'sum_check_failed',  -- Sum check failed (needs manual review)
    'manual_review',     -- Waiting for manual review
    'success',           -- Processing successful
    'failed'             -- Processing failed (OCR or LLM completely failed)
  ));

-- Step 4: Update column comment
COMMENT ON COLUMN receipts.current_stage IS 
  'Current processing stage: ocr_google, ocr_aws, llm_primary, llm_fallback, sum_check_failed, manual_review, success, failed';

-- Step 5: Verify migration success
DO $$
DECLARE
    invalid_count INTEGER;
    null_count INTEGER;
BEGIN
    -- Check for invalid values
    SELECT COUNT(*) INTO invalid_count
    FROM receipts
    WHERE current_stage NOT IN (
        'ocr_google', 'ocr_aws', 'llm_primary', 'llm_fallback', 
        'sum_check_failed', 'manual_review', 'success', 'failed'
    );
    
    -- Check for NULL values
    SELECT COUNT(*) INTO null_count
    FROM receipts
    WHERE current_stage IS NULL;
    
    IF invalid_count > 0 OR null_count > 0 THEN
        RAISE EXCEPTION 'Migration failed: % invalid rows, % NULL rows', invalid_count, null_count;
    END IF;
    
    RAISE NOTICE 'Migration 008 completed successfully. All rows have valid current_stage values.';
END $$;

COMMIT;
