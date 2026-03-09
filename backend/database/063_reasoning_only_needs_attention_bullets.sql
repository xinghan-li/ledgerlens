-- ============================================
-- Migration 063: reasoning only needs-attention bullets + newline per bullet
-- ============================================
-- vision_primary: When needs_review, _metadata.reasoning should list ONLY issues
-- requiring user action (e.g. date/time not found). Do NOT include "Sum check passed",
-- "Item count matches". One bullet per line, end each with \n for readability.
-- ============================================

BEGIN;

UPDATE prompt_library
SET content = REPLACE(
  content,
  E'   - Set _metadata.reasoning to a plain-English explanation of your validation_status and confidence decisions. Be specific: name which items or fields caused issues. Use dollar amounts in reasoning (e.g. $198.59), not cents.\n   - When validation_status is "needs_review", format _metadata.reasoning as short bullet points, for example:\n     • Sum check: passed / not passed. Calculated sum $X.XX, subtotal $Y.YY, discrepancy $Z.ZZ.\n     • Item count: passed / not passed. Receipt shows X items, extracted Y items.\n     • Date/time: found / not found. (If not found: date and time not found on receipt; please enter manually.)',
  E'   - When validation_status is "needs_review", put in _metadata.reasoning ONLY the issues that require user action. Do NOT include bullets for checks that passed (e.g. do not write "Sum check passed", "Item count matches"). Include only: sum check failed (with dollar details), item count mismatch, or date/time not found. Format as bullet points, one per line, and end each bullet with a newline (\\n). Example: "• Date/time: not found on receipt; please enter manually.\\n"\n   - When validation_status is "pass", you may leave _metadata.reasoning empty or omit it.'
)
WHERE key = 'vision_primary' AND is_active = TRUE;

COMMIT;
