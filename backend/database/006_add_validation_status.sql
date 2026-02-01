-- ============================================
-- 006_add_validation_status.sql
-- Add validation_status field to receipt_processing_runs table
-- ============================================

-- Add validation_status column to receipt_processing_runs table
-- This field stores the validation_status from LLM output_payload._metadata.validation_status
-- Allows quick filtering of receipts that need manual review
ALTER TABLE receipt_processing_runs
ADD COLUMN validation_status TEXT;

-- Add check constraint to ensure only valid values
ALTER TABLE receipt_processing_runs
ADD CONSTRAINT receipt_processing_runs_validation_status_check
  CHECK (validation_status IS NULL OR validation_status IN ('pass', 'needs_review', 'unknown'));

-- Add index for quick filtering of needs_review items
CREATE INDEX receipt_processing_runs_validation_status_idx 
  ON receipt_processing_runs(validation_status) 
  WHERE validation_status = 'needs_review';

-- Add comment
COMMENT ON COLUMN receipt_processing_runs.validation_status IS 
  'Validation status from LLM output_payload._metadata.validation_status. Values: pass, needs_review, unknown. NULL for OCR stage records.';

-- ============================================
-- Data Backfill Notes
-- ============================================
-- NOTE: Data backfill operations have been moved to:
-- - backend/database/2026-01-31_MIGRATION_NOTES.md (Section 5.1)
-- 
-- To backfill validation_status from existing output_payload, see the migration notes.
