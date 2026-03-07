-- ============================================
-- Migration 056: allow current_stage = 'vision_store_specific' in receipt_status
--
-- Migration 055 added 'vision_store_specific' to receipt_processing_runs.stage,
-- but forgot to update the receipt_status.current_stage CHECK constraint.
-- This caused a 400 error when the workflow tried to set current_stage to
-- 'vision_store_specific' at the end of Costco second-round processing.
-- ============================================

BEGIN;

ALTER TABLE public.receipt_status
  DROP CONSTRAINT IF EXISTS receipt_status_current_stage_check;

ALTER TABLE public.receipt_status
  ADD CONSTRAINT receipt_status_current_stage_check
  CHECK (current_stage IN (
    'ocr', 'llm_primary', 'llm_fallback', 'manual',
    'rejected_not_receipt', 'pending_receipt_confirm',
    'vision_primary', 'vision_escalation', 'vision_store_specific'
  ));

COMMENT ON COLUMN public.receipt_status.current_stage IS
  'Current processing stage: ocr, llm_primary, llm_fallback, manual, rejected_not_receipt, pending_receipt_confirm, vision_primary, vision_escalation, vision_store_specific';

COMMIT;
