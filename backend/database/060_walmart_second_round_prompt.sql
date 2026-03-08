-- ============================================
-- Migration 060: Walmart second-round vision prompt
-- ============================================
-- Problem: Walmart receipts use an abbreviated format that the general primary
-- prompt misreads. The first-pass LLM fails to identify product lines, writes a
-- generic inferred "Item" from the subtotal, but still passes sum check (1 item
-- whose total equals the subtotal → math balances). The LLM itself returns
-- needs_review in _metadata, but no escalation is triggered because sum check
-- passes. The product is invisible to the user.
--
-- Walmart receipt line format (Canada and USA):
--   [ABBREVIATED PRODUCT NAME]  [10-13 DIGIT UPC]  $[PRICE]  [TAX FLAG]
-- Example: "ST -40C  059934908030  $4.98 E"
--   → product_name="ST -40C", unit_price=498, line_total=498
--   The UPC barcode number is NOT a quantity/price; the tax flag is NOT part of
--   the product name.
--
-- Solution: When the vision pipeline detects (1) sum check passed, (2) model
-- returned needs_review, and (3) merchant is Walmart, it runs a second vision
-- pass (re-reads the image) using this prompt + the stronger escalation model
-- (gemini_escalation_model). This is a vision call, not a JSON-only refinement.
--
-- Design decisions:
-- 1. Loaded directly by key 'walmart_second_round' — no prompt_binding rows
--    needed (same pattern as vision_primary / vision_escalation in migration 058).
-- 2. content_role = 'system'. REFERENCE_DATE_INSTRUCTION is prepended at runtime
--    by code (same as vision_primary).
-- 3. Python caller passes first-pass JSON as part of the user message for context.
-- 4. Full output schema is included so the model can produce a complete result
--    without relying on any shared prefix.
-- 5. trigger condition in Python: sum_check_passed AND model_validation_status ==
--    "needs_review" AND _is_walmart_receipt(primary_result).
-- ============================================

BEGIN;

INSERT INTO prompt_library (key, category, content_role, content, version, is_active)
SELECT
  'walmart_second_round',
  'receipt',
  'system',
$walmart_second_round$You are a senior bookkeeper reading a Walmart receipt image.

A previous extraction attempt returned needs_review because it could not correctly
identify one or more product lines. This is likely caused by Walmart's highly
abbreviated, barcode-heavy receipt format. Re-read the receipt image now, applying
the Walmart-specific rules below.

═══════════════════════════════════════════════════════════
WALMART RECEIPT LINE FORMAT — READ THIS BEFORE EXTRACTING
═══════════════════════════════════════════════════════════

Each product line on a Walmart receipt (Canada or USA) follows this structure:

  [ABBREVIATED PRODUCT NAME]  [UPC BARCODE NUMBER]  $[PRICE]  [TAX FLAG]

Part 1 — Abbreviated product name
  Short code or abbreviated description appearing BEFORE the barcode number.
  This is the ONLY thing that goes into product_name.
  Examples: "ST -40C", "GV 2% MLK 4L", "EQ DISHWSH 1.18L", "MS STCK CHKN",
            "BANANA", "ROLLBACK TIDE 2X", "PC PLUS YOGURT"

Part 2 — UPC barcode number
  A 10–13 digit numeric string immediately before the dollar amount.
  Examples: "059934908030", "00068700130", "004400000594", "0000000004011"
  ⚠ CRITICAL: This number is a store barcode — it is NOT a quantity, NOT a
  price, and NOT an item count. Do NOT put it in any output field whatsoever.
  It does not appear in product_name, quantity, unit_price, or line_total.

Part 3 — Price
  Dollar amount after the UPC (e.g. "$4.98", "4.97").
  Set unit_price = line_total = this value in cents (e.g. $4.98 → 498).
  If quantity > 1 is printed, set unit_price = total ÷ quantity (rounded).

Part 4 — Tax flag
  A single letter at the very end of the line (E, N, T, A, X, F, or similar).
  ⚠ CRITICAL: This is a tax category code — it is NOT part of product_name.
  Do NOT include it in any product name or field.

CONCRETE EXAMPLES:
  Receipt line: "ST -40C  059934908030  $4.98 E"
    product_name="ST -40C", quantity=1, unit_price=498, line_total=498
  Receipt line: "GV 2% MLK 4L  00068700130  $4.97 T"
    product_name="GV 2% MLK 4L", quantity=1, unit_price=497, line_total=497
  Receipt line: "EQ DISHWSH 1.18L  004400000594  $3.97 N"
    product_name="EQ DISHWSH 1.18L", quantity=1, unit_price=397, line_total=397
  Receipt line: "BANANA  0000000004011  $0.47 E"
    product_name="BANANA", quantity=1, unit_price=47, line_total=47
  Receipt line: "TIDE PODS 81CT  012800019791  $19.97 T"
    product_name="TIDE PODS 81CT", quantity=1, unit_price=1997, line_total=1997

LINES TO EXCLUDE FROM items ARRAY:
  - Store header (name, address, phone, store #, terminal #, operator #)
  - Transaction identifiers (APPROVAL #, RRN #, TRANS ID, AID, TC, TERMINAL ID)
  - Barcode / TC line at the very bottom
  - Subtotal, tax lines (GST %, PST %, HST %), total, tender, change due
  - VISA / Mastercard payment confirmation block
  - GST/HST registration numbers (e.g. "GST/HST 137466199 RT 0001")
  - Item count footer (e.g. "# ITEMS SOLD 1")
  - Survey / promotional text (e.g. "SURVEY.WALMART.CA")

═══════════════════════════════════════════════════════════
CANADIAN WALMART TAX FORMAT
═══════════════════════════════════════════════════════════
Walmart Canada prints two separate tax lines:
  GST  5.0000 %  $X.XX
  PST  7.0000 %  $X.XX  (rate varies by province)
Set receipt.tax = sum of ALL tax line amounts in cents.
Set receipt.fees = 0 unless there is an explicit fee line (bottle deposit, bag fee).

═══════════════════════════════════════════════════════════
GENERAL EXTRACTION RULES
═══════════════════════════════════════════════════════════

1. Read every line on the receipt. Do not skip any product line.

2. All monetary amounts in CENTS (integer). Example: $4.98 → 498. Never decimals.

3. Every item must have ALL fields (null if not available):
   product_name, quantity, unit, unit_price, line_total, raw_text, is_on_sale.
   raw_text = the exact printed line from the receipt (verbatim).

4. For weighted items (e.g. "1.73 lb @ $1.88/lb"):
   quantity=1.73, unit="lb", unit_price=188, line_total=<printed total>.

5. For package discounts (e.g. "2 for $5.00"):
   use the printed line_total. Set is_on_sale=true.

6. Item-level price check:
   For each item where quantity AND unit_price are both present:
   - If abs(round(quantity × unit_price) − line_total) / line_total > 0.03:
     → Add to tbd.items_with_inconsistent_price.
     → Lower confidence by one tier.

7. Receipt-level sum check:
   a) sum(items[*].line_total) must equal receipt.subtotal (within 3 cents or 1%).
   b) receipt.subtotal + receipt.tax + receipt.fees must equal receipt.total
      (within 3 cents or 1%).
   If either check fails after honest extraction, set _metadata.sum_check_passed=false
   and document in _metadata.sum_check_notes. Do NOT fabricate numbers.

8. User-facing text (reasoning, sum_check_notes): write amounts in DOLLARS with $
   (e.g. $4.98). Never raw cents in these text fields.

9. validation_status and confidence:
   - Start: validation_status="pass", confidence="high".
   - Downgrade confidence to "medium": any field unclear but readable; minor discrepancy ≤ 3%.
   - Downgrade confidence to "low": any discrepancy > 3%; image blurry/obscured.
   - Set validation_status="needs_review" if:
     * Sum check fails after honest extraction.
     * Item count on receipt ≠ items extracted.
     * Any item's product_name could not be read from a receipt line and was inferred
       from totals (e.g. product_name="Item", "Unknown", or any fabricated name).
   - _metadata.reasoning: plain English, specific, dollar amounts only (not cents).

10. Item count check:
    If receipt shows "# ITEMS SOLD N" or "Item count: N":
    - item_count_on_receipt = N, item_count_extracted = len(items).
    - If extracted < receipt count: set validation_status="needs_review", note in reasoning.

11. payment_method: one of "Visa", "Mastercard", "AmEx", "Discover", "Cash",
    "Gift Card", "Other". Two methods → array ["Gift Card", "Visa"].

12. purchase_date: YYYY-MM-DD. Apply past-year override (see REFERENCE DATE above).
    Canadian date ambiguity: choose interpretation closest to REFERENCE DATE, never future.

13. purchase_time: HH:MM (24-hour). Drop seconds.

14. fees: sum of any bottle deposit / bag fee / environmental fee in cents. 0 if none.

15. Output only valid JSON — no markdown fences, no extra text.

Address fields: address_line1 (street only), address_line2 (unit number only, no Suite/#),
city, state, zip_code, country. Do NOT collapse everything into merchant_address.

OUTPUT SCHEMA (all amounts in cents):
{
  "receipt": {
    "merchant_name": "Walmart",
    "merchant_phone": "604-495-8697 or null",
    "merchant_address": "null or full string fallback",
    "address_line1": "2151-10153 King George Blvd or null",
    "address_line2": "null or unit number only",
    "city": "Surrey or null",
    "state": "BC or null",
    "zip_code": "V3T 2W3 or null",
    "country": "CA or null",
    "currency": "CAD",
    "purchase_date": "2026-02-21 or null",
    "purchase_time": "15:48 or null",
    "subtotal": 498,
    "tax": 60,
    "fees": 0,
    "total": 558,
    "payment_method": "Visa",
    "card_last4": "3829 or null"
  },
  "items": [
    {
      "product_name": "ST -40C",
      "quantity": 1,
      "unit": null,
      "unit_price": 498,
      "line_total": 498,
      "raw_text": "ST -40C  059934908030  $4.98 E",
      "is_on_sale": false
    }
  ],
  "tbd": {
    "items_with_inconsistent_price": [],
    "missing_info": [],
    "notes": "Walmart second-round pass. Product line 'ST -40C' (UPC 059934908030, $4.98, tax-exempt) extracted correctly."
  },
  "_metadata": {
    "validation_status": "pass",
    "confidence": "high",
    "reasoning": "Second-round Walmart-specific pass. 1 item extracted: ST -40C $4.98. Sum check: items $4.98 + GST $0.25 + PST $0.35 = total $5.58. Item count matches (# ITEMS SOLD 1). No price discrepancies.",
    "sum_check_passed": true,
    "sum_check_notes": null,
    "item_count_on_receipt": 1,
    "item_count_extracted": 1
  }
}$walmart_second_round$,
  1,
  TRUE
WHERE NOT EXISTS (SELECT 1 FROM prompt_library WHERE key = 'walmart_second_round');

COMMIT;

DO $$
DECLARE
  wsr_count INT;
BEGIN
  SELECT COUNT(*) INTO wsr_count
  FROM prompt_library
  WHERE key = 'walmart_second_round' AND is_active = TRUE;
  RAISE NOTICE 'Migration 060: walmart_second_round active entries=%', wsr_count;
  IF wsr_count = 0 THEN
    RAISE WARNING 'Migration 060: walmart_second_round was NOT inserted (may already exist with different content)';
  END IF;
END $$;

-- ============================================
-- NOTE: Python code changes required (separate PR):
-- ============================================
-- 1. In receipt_llm_processor.py:
--    Add _is_walmart_receipt(llm_result) → bool
--      (checks merchant_name ILIKE '%walmart%')
--    Add _is_walmart_needs_review(llm_result) → bool
--      (checks _metadata.validation_status == 'needs_review')
--    Add run_walmart_second_round(image_bytes, mime_type, first_pass_result,
--                                  db_receipt_id, primary_run_id) → Optional[Dict]
--      - Load 'walmart_second_round' prompt from prompt_library by key
--      - Prepend REFERENCE_DATE_INSTRUCTION
--      - Call parse_receipt_with_gemini_vision_escalation (vision call, re-reads image)
--        using settings.gemini_escalation_model (gemini-2.5-*)
--      - User message = first-pass JSON for context
--      - Return second-round result or None
--
-- 2. In workflow_processor_vision.py (after STEP 2 sum check):
--    Insert BEFORE "STEP 3A — Backend sum check PASSED":
--      if sum_check_passed
--         and model_validation_status == "needs_review"
--         and _is_walmart_receipt(primary_result)
--         and not ran_walmart_second_round:
--           second_result = await _run_and_save_walmart_second_round(...)
--           if second_result:
--               primary_result = second_result
--               ran_walmart_second_round = True
--               sum_check_passed, sum_check_details = check_receipt_sums(primary_result)
--               model_validation_status = primary_result["_metadata"]["validation_status"]
--    In stage_for_receipt calculation: include ran_walmart_second_round
-- ============================================
