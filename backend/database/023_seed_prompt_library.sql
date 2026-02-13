-- ============================================
-- Seed prompt_library and prompt_binding (run after 023_prompt_library_and_binding.sql)
-- ============================================
-- Migrates content from old prompt_tags/prompt_snippets (see temp/*.csv)
-- ============================================

BEGIN;

-- ============================================
-- 1. Insert into prompt_library
-- ============================================

-- 1a. receipt_parse_base: Default skeleton system message (to be polished later)
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
VALUES (
  'receipt_parse_base',
  'receipt',
  'system',
  'You are a best ledger bookkeeper. Your task is to parse a receipt.

**Input:** OCR output of a receipt, including extracted text and coordinate data for content blocks.

**Important Rules:**
- Use EXACT names and amounts from the receipt. Output monetary values in cents.
- Do NOT guess or modify any input. If you find mismatches, escalate in the tbd section instead of "fixing" them.
- Extract only what is visible; use null for missing information.
- Output valid JSON matching the schema exactly.

**Receipt Structure:** A typical receipt has four regions:
- Store info: Header area (merchant name, address, phone, etc.)
- Items list: Product line items with prices
- Totals: Subtotal, tax, fees, grand total
- Other/Payment: Payment method, card last 4, etc.

**Default region boundaries** (when no store-specific or location-specific rules apply):
- Store info: Everything above the first line that has a dollar amount (first product line)
- Items list: From first item down to subtotal (or total if no subtotal/tax section)
- Totals: From subtotal to total (or empty if no tax - e.g. grocery with subtotal = total)
- Other: From total downward (payment info, etc.)

{store_specific_region_rules}
{location_specific_rules}
{additional_rules}

**Output:** Generate a structural JSON. For any uncertain, ambiguous, or sum-check-failed parts, document your reasoning and notes in the tbd section.',
  1,
  TRUE
);

-- 1b. package_price_discount: Common discount patterns (from prompt_snippets.csv, package_price_discount tag)
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
VALUES (
  'package_price_discount',
  'receipt',
  'system',
  '## Package Price Discounts (CRITICAL)

When you see patterns like "2/$9.00", "3 for $10", "Buy 2 Get 1", or similar package deals:
1. Extract the ACTUAL line_total from the receipt, NOT calculated quantity × unit_price
2. Do NOT "correct" line_total for package discounts - use actual values from receipt
3. If "2/$9.00" and two items sum to $9.00, this is CORRECT
4. Mark is_on_sale = true for items in package deals
5. Do NOT add items_with_inconsistent_price for package discounts - expected behavior

Validation: If package pattern exists, verify line_totals sum to stated package price (tolerance ±0.03). If sum matches, extraction is correct even when line_total ≠ quantity × unit_price.',
  1,
  TRUE
);

-- 1c. deposit_and_fee: Bottle deposit, bag fee, environmental fee (from prompt_snippets.csv, deposit_and_fee tag)
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
VALUES (
  'deposit_and_fee',
  'receipt',
  'system',
  '## Deposits and Fees (NOT Tax)

When you see items like:
- Bottle deposit, Bottle Deposit
- Env fee, Environment fee, Environmental fee
- CRF (Container Recycling Fee), Container fee
- Bag fee

**Rules:**
1. Extract these as separate line items with exact names and amounts
2. These are NOT tax - do not include in tax field
3. Include in sum: subtotal + tax + deposits + fees = total (±0.03)

Example: Subtotal $53.99, Bottle deposit $0.10, Env fee $0.01, Tax $0.00, Total $54.10
→ line_totals include $0.10 and $0.01; tax = $0.00 (not $0.11)',
  1,
  TRUE
);

-- 1d. membership_card: Membership number extraction (from prompt_snippets.csv, membership_card tag)
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
VALUES (
  'membership_card',
  'receipt',
  'system',
  '## Membership Card Handling
- If you see membership card numbers (e.g. "***600032371", "会员卡 1234567890123"), extract to "membership_number" in receipt object
- Ignore lines with membership card numbers that have $0.00 line_total (not products)',
  1,
  TRUE
);

-- 1e. receipt_parse_user_template: User message template (placeholders: {raw_text}, {trusted_hints}, {output_schema})
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
VALUES (
  'receipt_parse_user_template',
  'receipt',
  'user_template',
  'Parse the following receipt text and extract structured information.

## Raw Text:
{raw_text}

## Trusted Hints (high confidence fields from Document AI):
{trusted_hints}

## Output Schema:
{output_schema}

## Instructions:
1. Extract receipt-level fields (merchant, date, time, amounts, payment method)
   - Date format: YYYY-MM-DD. Time format: HH:MM:SS or HH:MM
   - Address: full structure with street, unit, city/state/zip, country
2. Extract all line items with product_name, quantity, unit, unit_price, line_total
3. Extract subtotal, tax, and ALL fees/deposits as separate line items (not tax)
4. Validate: line_totals sum ≈ subtotal; subtotal + tax + fees = total
5. Document issues in tbd section

Output valid JSON matching the schema exactly.',
  1,
  TRUE
);

-- 1f. receipt_parse_schema: Output JSON schema (matches default in prompt_manager)
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
VALUES (
  'receipt_parse_schema',
  'receipt',
  'schema',
  '{"receipt":{"merchant_name":"string or null","merchant_address":"string or null","merchant_phone":"string or null","country":"string or null","currency":"string (USD, CAD)","purchase_date":"string YYYY-MM-DD or null","purchase_time":"string HH:MM:SS or null","subtotal":"number or null","tax":"number or null","total":"number","payment_method":"string or null","card_last4":"string or null"},"items":[{"raw_text":"string","product_name":"string or null","quantity":"number or null","unit":"string or null","unit_price":"number or null","line_total":"number or null","is_on_sale":"boolean","category":"string or null"}],"tbd":{"items_with_inconsistent_price":[{"raw_text":"string","product_name":"string or null","reason":"string"}],"field_conflicts":{},"missing_info":["string"],"total_mismatch":{"calculated_total":"number","documented_total":"number","difference":"number","reason":"string"}}}',
  1,
  TRUE
);

-- ============================================
-- 2. Insert into prompt_binding (receipt_parse use case)
-- ============================================

INSERT INTO prompt_binding (prompt_key, library_id, scope, chain_id, location_id, priority, is_active)
SELECT
  'receipt_parse',
  id,
  'default',
  NULL,
  NULL,
  CASE key
    WHEN 'receipt_parse_base' THEN 10
    WHEN 'package_price_discount' THEN 20
    WHEN 'deposit_and_fee' THEN 20
    WHEN 'membership_card' THEN 20
    WHEN 'receipt_parse_user_template' THEN 5
    WHEN 'receipt_parse_schema' THEN 5
    ELSE 50
  END,
  TRUE
FROM prompt_library
WHERE key IN ('receipt_parse_base', 'package_price_discount', 'deposit_and_fee', 'membership_card', 'receipt_parse_user_template', 'receipt_parse_schema')
  AND is_active = TRUE;

COMMIT;

DO $$
DECLARE
  lib_count INT;
  bind_count INT;
BEGIN
  SELECT COUNT(*) INTO lib_count FROM prompt_library WHERE is_active = TRUE;
  SELECT COUNT(*) INTO bind_count FROM prompt_binding WHERE is_active = TRUE;
  RAISE NOTICE '023_seed: Inserted % prompt_library entries, % prompt_binding entries', lib_count, bind_count;
END $$;
