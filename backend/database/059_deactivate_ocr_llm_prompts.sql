-- ============================================
-- Migration 059: Soft-delete OCR+LLM-only prompt_library entries
-- ============================================
-- Shadow legacy runs in workflow_processor_vision.py have been disabled.
-- The OCR+LLM pipeline (Route A) is fully deprecated.
-- These keys are only used by:
--   - format_prompt() → prompt_key='receipt_parse' (OCR+LLM first pass)
--   - get_debug_prompt_system() → prompt_key='receipt_parse_debug_ocr' / 'receipt_parse_debug_vision'
--
-- Vision pipeline (Route B) uses only:
--   receipt_parse_second (common + costco_second_round + real_canadian_superstore_rules + trader_joes_second_round)
--   classification (via categorize_receipt → suggest_classifications)
--   vision_primary     (added in migration 058)
--   vision_escalation  (added in migration 058)
--
-- Soft-delete: is_active=FALSE preserves history and FK integrity.
-- ============================================

BEGIN;

UPDATE prompt_library
SET is_active = FALSE, updated_at = NOW()
WHERE key IN (
  'receipt_parse_base',
  'package_price_discount',
  'deposit_and_fee',
  'membership_card',
  'receipt_parse_user_template',
  'receipt_parse_schema',
  'receipt_parse_debug_ocr',
  'receipt_parse_debug_vision'
)
AND is_active = TRUE;

COMMIT;

DO $$
DECLARE
  deactivated INT;
BEGIN
  SELECT COUNT(*) INTO deactivated
  FROM prompt_library
  WHERE key IN (
    'receipt_parse_base', 'package_price_discount', 'deposit_and_fee',
    'membership_card', 'receipt_parse_user_template', 'receipt_parse_schema',
    'receipt_parse_debug_ocr', 'receipt_parse_debug_vision'
  )
  AND is_active = FALSE;
  RAISE NOTICE 'Migration 059: % OCR+LLM-only prompt_library entries deactivated', deactivated;
END $$;
