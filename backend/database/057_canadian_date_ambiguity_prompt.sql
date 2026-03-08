-- ============================================
-- Migration 057: Prompt updates (Canadian date, store-specific rules)
--
-- 1. Canadian date ambiguity: YY/MM/DD vs MM/DD/YY — prefer date closest to reference.
-- 2. Real Canadian Superstore: store-specific prompt — date format is year/month/day.
-- 3. Costco: LIQUOR LITER line after liquor = tax, not an item (do not count in item count).
-- 4. Trader Joe's: second-round prompt — item count is by unit (5 bananas = 5 items).
-- ============================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Update receipt_parse_user_template: Canadian date ambiguity rule
-- ---------------------------------------------------------------------------
UPDATE prompt_library
SET content = 'Parse the following receipt text and extract structured information.

## Raw Text:
{raw_text}

## Trusted Hints (high confidence fields from Document AI):
{trusted_hints}

## Output Schema:
{output_schema}

## Instructions:
1. Extract receipt-level fields (merchant, date, time, amounts, payment method)
   - Date format: YYYY-MM-DD. Time format: HH:MM:SS or HH:MM
   - Canadian date ambiguity: Some Canadian stores print dates as YY/MM/DD (e.g. "26/03/07" = 2026-03-07) rather than MM/DD/YY. If the store is in Canada and both YY/MM/DD and MM/DD/YY produce valid dates, choose the interpretation closest to the reference date (today).
   - Address: full structure with street, unit, city/state/zip, country
2. Extract all line items with product_name, quantity, unit, unit_price, line_total
3. Extract subtotal, tax, and ALL fees/deposits as separate line items (not tax)
4. Validate: line_totals sum ≈ subtotal; subtotal + tax + fees = total
5. Document issues in tbd section

Output valid JSON matching the schema exactly.',
    version = version + 1,
    updated_at = NOW()
WHERE key = 'receipt_parse_user_template'
  AND is_active = TRUE;

-- ---------------------------------------------------------------------------
-- 2. Real Canadian Superstore: store-specific prompt (date = year/month/day)
-- ---------------------------------------------------------------------------
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT
  'real_canadian_superstore_rules',
  'receipt',
  'system',
  '## Real Canadian Superstore — date format

At Real Canadian Superstore, the receipt date is printed in **year/month/day** order (e.g. YYYY/MM/DD or YY/MM/DD). Interpret dates accordingly; do not use US-style month/day/year.',
  1,
  TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'real_canadian_superstore_rules');

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
WHERE pl.key = 'real_canadian_superstore_rules' AND pl.is_active = TRUE
  AND (sc.name ILIKE '%real canadian superstore%' OR sc.normalized_name ILIKE '%real_canadian_superstore%')
  AND NOT EXISTS (
    SELECT 1 FROM prompt_binding pb
    WHERE pb.prompt_key = 'receipt_parse_second' AND pb.library_id = pl.id AND pb.scope = 'chain' AND pb.chain_id = sc.id
  );

-- ---------------------------------------------------------------------------
-- 3. Costco: LIQUOR LITER tax line — not an item, do not count in item count
-- ---------------------------------------------------------------------------
UPDATE prompt_library
SET content = content || E'\n\n**LIQUOR LITER tax (e.g. WA):** If you see a line that says ''LIQUOR LITER'' (or similar) **immediately after** a liquor/wine product line, that line is a **tax/fee**, not a product. Do **not** add it to the items array and do **not** count it toward item count. Only the liquor product above it is an item.',
  version = version + 1,
  updated_at = NOW()
WHERE key = 'costco_second_round' AND is_active = TRUE;

-- ---------------------------------------------------------------------------
-- 4. Trader Joe''s: second-round prompt (item count = by unit)
-- ---------------------------------------------------------------------------
INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT
  'trader_joes_second_round',
  'receipt',
  'system',
  '## Trader Joe''s — second pass (item count by unit)

At Trader Joe''s, the receipt''s item count is **by actual product units**: e.g. 5 bananas count as 5 items, not 1 line. If the receipt shows "Item count: N" (or similar) and your extracted count does not match, **go back** and ensure every quantity is fully reflected so that the total number of units (sum of quantities, or one row per unit if you list each unit) equals N. Do not leave out quantities to match a mistaken interpretation.',
  1,
  TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'trader_joes_second_round');

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
WHERE pl.key = 'trader_joes_second_round' AND pl.is_active = TRUE
  AND (sc.name ILIKE '%trader joe%' OR sc.normalized_name ILIKE '%trader_joe%')
  AND NOT EXISTS (
    SELECT 1 FROM prompt_binding pb
    WHERE pb.prompt_key = 'receipt_parse_second' AND pb.library_id = pl.id AND pb.scope = 'chain' AND pb.chain_id = sc.id
  );

COMMIT;

DO $$
DECLARE
  updated_count INT;
  rcs_bind INT;
  tj_bind INT;
BEGIN
  SELECT COUNT(*) INTO updated_count
  FROM prompt_library WHERE key = 'receipt_parse_user_template' AND is_active = TRUE;
  SELECT COUNT(*) INTO rcs_bind FROM prompt_binding pb JOIN prompt_library pl ON pl.id = pb.library_id
  WHERE pl.key = 'real_canadian_superstore_rules' AND pb.prompt_key = 'receipt_parse_second';
  SELECT COUNT(*) INTO tj_bind FROM prompt_binding pb JOIN prompt_library pl ON pl.id = pb.library_id
  WHERE pl.key = 'trader_joes_second_round' AND pb.prompt_key = 'receipt_parse_second';
  RAISE NOTICE 'Migration 057: receipt_parse_user_template updated=%; Real Canadian Superstore second-round binds=%; Trader Joe''s second-round binds=%', updated_count, rcs_bind, tj_bind;
END $$;
