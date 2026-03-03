-- ============================================
-- Migration 041: Seed prompt_library for LLM debug cascade
-- ============================================
-- Purpose: Add receipt_parse_debug_ocr and receipt_parse_debug_vision for
-- Sum-check failure path: debug with raw OCR, then with image + reason.
-- See docs/architecture/RECEIPT_WORKFLOW_CASCADE.md
--
-- Run after: 040
-- ============================================

BEGIN;

-- Debug step 1: LLM with raw OCR only (no image)
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT 'receipt_parse_debug_ocr', 'receipt', 'system',
  'The previous answer had sum/total issues. Compare the original OCR JSON and the summarized JSON below. Can you see where the problem is?
- If you can identify and fix the issue: correct the output and return the full receipt JSON.
- If you do not have enough confidence: escalate by setting top-level "reason" to your finding and still output best-effort JSON. The next step will send you the receipt image to read from.',
  1, TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'receipt_parse_debug_ocr');

-- Debug step 2: LLM with image (same conversation), must output reason if escalating
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT 'receipt_parse_debug_vision', 'receipt', 'system',
  'You are now being given the receipt image to read from. Use the image together with the previous OCR and summarized JSON to produce the correct receipt JSON.
- If you can extract correctly: output the full receipt JSON; set "reason" to null or omit.
- If you cannot be confident: set top-level "reason" to your finding and output best-effort JSON. Do not output ambiguous or uncertain structural answers.',
  1, TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'receipt_parse_debug_vision');

-- Bind to default scope
INSERT INTO prompt_binding (prompt_key, library_id, scope, priority, is_active)
SELECT 'receipt_parse_debug_ocr', pl.id, 'default', 10, TRUE
FROM prompt_library pl
WHERE pl.key = 'receipt_parse_debug_ocr' AND pl.is_active = TRUE
  AND NOT EXISTS (SELECT 1 FROM prompt_binding pb WHERE pb.library_id = pl.id AND pb.prompt_key = 'receipt_parse_debug_ocr')
LIMIT 1;

INSERT INTO prompt_binding (prompt_key, library_id, scope, priority, is_active)
SELECT 'receipt_parse_debug_vision', pl.id, 'default', 10, TRUE
FROM prompt_library pl
WHERE pl.key = 'receipt_parse_debug_vision' AND pl.is_active = TRUE
  AND NOT EXISTS (SELECT 1 FROM prompt_binding pb WHERE pb.library_id = pl.id AND pb.prompt_key = 'receipt_parse_debug_vision')
LIMIT 1;

COMMIT;
