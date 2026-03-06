-- ============================================
-- Migration 052: Second-round prompts (store-matched refinement)
-- ============================================
-- For the two-phase vision flow: first LLM pass is image-only (general prompt);
-- after store match from first-pass JSON, second pass uses image + JSON with
-- prompt_key receipt_parse_second. This migration adds:
-- - Common prefix (receipt_parse_second_common): corrected input, suspicious
--   corrections, unclear text → guess but state in reasoning. Prepended for
--   every store that gets a second round.
-- - Costco second-round (costco_second_round): discount line merge into
--   previous item, original_price, is_on_sale, sum check after merge.
--
-- Legacy OCR+LLM flow gets no new prompts and is deprecated.
-- See: backend/database/documents/STORE_SPECIFIC_PROMPTS.md
-- ============================================

BEGIN;

-- ============================================
-- 1. Common second-round prefix (applies to ANY store that gets second round)
-- ============================================
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT
  'receipt_parse_second_common',
  'receipt',
  'system',
  '## Second pass — corrected / pre-filled input

You are given a first-pass JSON and the same receipt image. The JSON may have been corrected for store/address and for text that was unclear on the original receipt (e.g. black pen marks or faint print). That correction can sometimes introduce errors.

**Suspicious corrections:** If you see something that looks wrong or inconsistent (e.g. a product name that doesn''t match the image, a number that seems off, or text that looks like an over-correction), do **not** change it yourself. In the `reasoning` field, list each issue as a **bullet point** so the user can decide (e.g. "• Possible over-correction: product name ''XXX'' may have been filled from DB; please confirm against image.").

**Unclear text (e.g. vertical faint/crease/pen):** Sometimes receipt print is faint, creased, or crossed out (often along the vertical axis). If you are not confident in a specific word or number (e.g. you estimate your confidence below about 0.4), you **may still guess**, but in the `reasoning` field you **must** state which location or word was unclear and that your value there is a guess (e.g. "• Unclear: the word in the middle of the items list (approx. after ''ORANGES'') was faint; value ''XXX'' is a guess (confidence < 0.4).").',
  1,
  TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'receipt_parse_second_common');

-- Update existing receipt_parse_second_common to remove item-count paragraph (now appended in code only when needed)
UPDATE prompt_library
SET content = '## Second pass — corrected / pre-filled input

You are given a first-pass JSON and the same receipt image. The JSON may have been corrected for store/address and for text that was unclear on the original receipt (e.g. black pen marks or faint print). That correction can sometimes introduce errors.

**Suspicious corrections:** If you see something that looks wrong or inconsistent (e.g. a product name that doesn''t match the image, a number that seems off, or text that looks like an over-correction), do **not** change it yourself. In the `reasoning` field, list each issue as a **bullet point** so the user can decide (e.g. "• Possible over-correction: product name ''XXX'' may have been filled from DB; please confirm against image.").

**Unclear text (e.g. vertical faint/crease/pen):** Sometimes receipt print is faint, creased, or crossed out (often along the vertical axis). If you are not confident in a specific word or number (e.g. you estimate your confidence below about 0.4), you **may still guess**, but in the `reasoning` field you **must** state which location or word was unclear and that your value there is a guess (e.g. "• Unclear: the word in the middle of the items list (approx. after ''ORANGES'') was faint; value ''XXX'' is a guess (confidence < 0.4).").',
  updated_at = now()
WHERE key = 'receipt_parse_second_common';

-- ============================================
-- 2. Costco second-round (discount merge + sum check)
-- ============================================
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT
  'costco_second_round',
  'receipt',
  'system',
  '## Costco — second pass (refinement)

**Costco discount lines:** On this receipt, a discount often appears on the **line immediately below** a product, in the form: slash + digits (e.g. `/00000000`) then an amount with a minus (e.g. `2.00-`). That line means: **apply this discount to the line above**; it is **not** a separate product.

**What you must do:**
- **Merge** the discount into the **previous** item: set that item''s `line_total` = (original price − discount) in **cents**. Example: previous item was 9.99, discount line shows 2.00- → that item''s `line_total` = 799 (7.99); do **not** create a new row for 2.00-.
- Set that item''s `is_on_sale` = true and `original_price` = the pre-discount price in cents (e.g. 999 for 9.99).
- Do **not** create a separate product row for the discount line.

**After merging discounts**, ensure the sum of items'' `line_total` still matches receipt subtotal/total within the usual tolerance; if not, list the mismatch in `reasoning` (e.g. "• Sum mismatch: items sum to X, receipt total Y; difference Z.").

Output the refined JSON with discounts aggregated as above.',
  1,
  TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'costco_second_round');

-- ============================================
-- 3. Bind common prefix as default for receipt_parse_second (prepended for every store)
-- ============================================
INSERT INTO prompt_binding (prompt_key, library_id, scope, chain_id, location_id, priority, is_active)
SELECT
  'receipt_parse_second',
  pl.id,
  'default',
  NULL,
  NULL,
  10,
  TRUE
FROM prompt_library pl
WHERE pl.key = 'receipt_parse_second_common' AND pl.is_active = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM prompt_binding pb
    WHERE pb.prompt_key = 'receipt_parse_second' AND pb.library_id = pl.id AND pb.scope = 'default'
  );

-- ============================================
-- 4. Bind Costco second-round to all Costco chains
-- ============================================
INSERT INTO prompt_binding (prompt_key, library_id, scope, chain_id, location_id, priority, is_active)
SELECT
  'receipt_parse_second',
  pl.id,
  'chain',
  sc.id,
  NULL,
  50,
  TRUE
FROM prompt_library pl
CROSS JOIN store_chains sc
WHERE pl.key = 'costco_second_round' AND pl.is_active = TRUE
  AND (sc.name ILIKE '%costco%' OR sc.normalized_name ILIKE '%costco%')
  AND NOT EXISTS (
    SELECT 1 FROM prompt_binding pb
    WHERE pb.prompt_key = 'receipt_parse_second' AND pb.library_id = pl.id AND pb.scope = 'chain' AND pb.chain_id = sc.id
  );

COMMIT;

DO $$
DECLARE
  common_bind INT;
  costco_bind INT;
BEGIN
  SELECT COUNT(*) INTO common_bind FROM prompt_binding pb JOIN prompt_library pl ON pl.id = pb.library_id
  WHERE pl.key = 'receipt_parse_second_common' AND pb.prompt_key = 'receipt_parse_second';
  SELECT COUNT(*) INTO costco_bind FROM prompt_binding pb JOIN prompt_library pl ON pl.id = pb.library_id
  WHERE pl.key = 'costco_second_round' AND pb.prompt_key = 'receipt_parse_second';
  RAISE NOTICE '052: receipt_parse_second_common default binds=%, costco_second_round chain binds=%', common_bind, costco_bind;
END $$;
