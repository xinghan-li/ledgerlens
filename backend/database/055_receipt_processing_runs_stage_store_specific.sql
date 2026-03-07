-- ============================================
-- Migration 055: allow stage = 'store_specific' in receipt_processing_runs
--
-- Costco (and future store-specific) second-round runs are saved with
-- stage = 'store_specific'. Python was updated to use this stage; the DB
-- CHECK constraint must allow it or INSERT fails.
-- ============================================

BEGIN;

-- Drop the existing stage check (constraint name from 001_schema_v2 inline CHECK)
ALTER TABLE public.receipt_processing_runs
  DROP CONSTRAINT IF EXISTS receipt_processing_runs_stage_check;

-- Re-add with store_specific included
ALTER TABLE public.receipt_processing_runs
  ADD CONSTRAINT receipt_processing_runs_stage_check
  CHECK (stage IN (
    'ocr', 'llm', 'manual', 'rule_based_cleaning',
    'vision_primary', 'vision_store_specific', 'vision_escalation', 'shadow_legacy'
  ));

COMMENT ON COLUMN public.receipt_processing_runs.stage IS
  'Processing stage: ocr, rule_based_cleaning, llm, manual, vision_primary, vision_store_specific, vision_escalation, shadow_legacy';

COMMIT;
