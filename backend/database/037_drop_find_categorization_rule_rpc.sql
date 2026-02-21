-- ============================================
-- Migration 037: Drop find_categorization_rule RPC
-- ============================================
-- Purpose: All matching logic has been moved to the backend (Python).
-- - Exact match: backend queries product_categorization_rules directly.
-- - Universal fuzzy: backend uses initial_categorization_rules.csv (same effect).
-- This migration removes the DB-side find_categorization_rule so no caller uses it.
-- update_rule_match_stats is kept (used by Classification Review etc.).
-- Run after: Backend has been deployed and tested with 037 not yet applied.
-- ============================================

BEGIN;

DROP FUNCTION IF EXISTS find_categorization_rule(TEXT, UUID, NUMERIC);

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 037 completed: dropped find_categorization_rule. Matching is backend-only.';
END $$;
