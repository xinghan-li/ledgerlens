-- ============================================
-- Fix receipts_current_stage_check constraint
-- ============================================
-- This script ensures the constraint matches the current code expectations
-- Run this in Supabase SQL Editor

BEGIN;

-- Step 1: Drop old constraint
ALTER TABLE receipts DROP CONSTRAINT IF EXISTS receipts_current_stage_check;

-- Step 2: Add correct constraint (matching migration 011)
-- Code expects: 'ocr', 'llm_primary', 'llm_fallback', 'manual'
ALTER TABLE receipts ADD CONSTRAINT receipts_current_stage_check
  CHECK (current_stage IN ('ocr', 'llm_primary', 'llm_fallback', 'manual'));

-- Step 3: Update column comment
COMMENT ON COLUMN receipts.current_stage IS 
  'Current processing stage: ocr (OCR processing), llm_primary (primary LLM), llm_fallback (fallback LLM), manual (manual review needed)';

-- Step 4: Verify constraint was added successfully
DO $$
DECLARE
    constraint_def TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid) INTO constraint_def
    FROM pg_constraint
    WHERE conrelid = 'receipts'::regclass
    AND conname = 'receipts_current_stage_check';
    
    IF constraint_def IS NOT NULL THEN
        RAISE NOTICE 'Constraint added successfully: %', constraint_def;
    ELSE
        RAISE EXCEPTION 'Failed to add constraint';
    END IF;
END $$;

COMMIT;

-- ============================================
-- Expected result:
-- NOTICE: Constraint added successfully: CHECK (current_stage = ANY (ARRAY['ocr'::text, 'llm_primary'::text, 'llm_fallback'::text, 'manual'::text]))
-- ============================================
