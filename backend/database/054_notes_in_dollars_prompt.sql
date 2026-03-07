-- ============================================
-- Migration 054: User-facing notes in dollars (all stores)
-- ============================================
-- Our database stores monetary amounts in CENTS. LLM-generated text that is
-- shown to the user (reason, tbd.notes, sum_check_notes, reasoning) must
-- express amounts in DOLLARS (e.g. $198.59), never raw cents (e.g. 19859).
-- This migration adds the rule to receipt-related prompt_library content.
-- ============================================

BEGIN;

-- Append the rule to receipt_parse_base (used for all receipt parsing when library is loaded)
UPDATE prompt_library
SET content = content || E'\n\n**User-facing notes (all stores):** In any free-text shown to the user (reason, tbd.notes, sum_check_notes, reasoning), always write monetary amounts in DOLLARS with $ (e.g. $198.59, $114.07). Never write raw cents (e.g. 19859, 11407) in these fields.'
WHERE key = 'receipt_parse_base';

-- receipt_parse_second_common: add the same rule for second-round / refinement prompts
UPDATE prompt_library
SET content = content || E'\n\n**User-facing notes:** In reasoning or any user-visible text, write amounts in dollars (e.g. $198.59), never raw cents (e.g. 19859).'
WHERE key = 'receipt_parse_second_common';

-- costco_second_round: ensure reasoning uses dollars
UPDATE prompt_library
SET content = content || E'\n\nIn `reasoning`, always use dollar amounts (e.g. $X.XX), never raw cents.'
WHERE key = 'costco_second_round';

COMMIT;
