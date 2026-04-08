-- ============================================
-- Migration 075: Add 'processing' to receipt_status check constraint
--
-- Problem: The async vision pipeline sets current_status='processing' when
-- creating a receipt row, but the check constraint only allows:
--   ('success', 'failed', 'needs_review', 'pending')
-- This causes every upload to fail with 23514 (check constraint violation).
--
-- Fix: Drop and recreate the constraint to include 'processing'.
-- ============================================

BEGIN;

ALTER TABLE receipt_status
  DROP CONSTRAINT IF EXISTS receipts_current_status_check;

ALTER TABLE receipt_status
  ADD CONSTRAINT receipts_current_status_check
  CHECK (current_status IN ('success', 'failed', 'needs_review', 'pending', 'processing'));

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 075 completed: receipts_current_status_check now includes processing.';
END $$;
