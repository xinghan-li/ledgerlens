-- ============================================
-- Migration 040: Allow stage 'rule_based_cleaning' in receipt_processing_runs
-- ============================================
-- Purpose: Support new workflow stage for rule-based cleaning (OCR -> RBSJ).
-- See docs/architecture/RECEIPT_WORKFLOW_CASCADE.md
--
-- Run after: 039
-- ============================================

BEGIN;

-- Drop existing stage check (exact name from 001_schema_v2 inline constraint)
ALTER TABLE receipt_processing_runs
  DROP CONSTRAINT IF EXISTS receipt_processing_runs_stage_check;

-- Allow: ocr | llm | manual | rule_based_cleaning
ALTER TABLE receipt_processing_runs
  ADD CONSTRAINT receipt_processing_runs_stage_check
  CHECK (stage IN ('ocr', 'llm', 'manual', 'rule_based_cleaning'));

COMMENT ON COLUMN receipt_processing_runs.stage IS
  'Processing stage: ocr, rule_based_cleaning (RBSJ), llm, manual';

COMMIT;
