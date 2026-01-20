-- Example extraction rules for different merchants
-- This demonstrates how to configure merchant-specific price extraction rules

-- 1. T&T Supermarket (uses FP format)
UPDATE merchant_prompts
SET extraction_rules = '{
  "price_patterns": [
    {
      "pattern": "FP\\s+\\$(\\d+\\.\\d{2})",
      "priority": 1,
      "description": "T&T specific FP price format",
      "flags": "IGNORECASE"
    },
    {
      "pattern": "\\$(\\d+\\.\\d{2})",
      "priority": 2,
      "description": "Generic dollar price format"
    }
  ],
  "skip_patterns": [
    "^TOTAL",
    "^Subtotal",
    "^Tax",
    "^Points",
    "^Reference",
    "^Trans:",
    "^Terminal:",
    "^CLERK",
    "^INVOICE:",
    "^REFERENCE:",
    "^AMOUNT",
    "^APPROVED",
    "^AUTH CODE",
    "^APPLICATION",
    "^Visa",
    "^VISA",
    "^Mastercard",
    "^Credit Card",
    "^CREDIT CARD",
    "^Customer Copy",
    "^STORE:",
    "^Ph:",
    "^www\\.",
    "^\\d{2}/\\d{2}/\\d{2}",
    "^\\*{3,}",
    "^Not A Member",
    "^立即下載",
    "^Get Exclusive",
    "^Enjoy Online",
    "^GROCERY$",
    "^PRODUCE$",
    "^DELI$",
    "^FOOD$"
  ],
  "special_rules": {
    "use_global_fp_match": true,
    "min_fp_count": 3,
    "category_identifiers": ["GROCERY", "PRODUCE", "DELI", "FOOD"]
  }
}'::jsonb
WHERE merchant_name ILIKE '%T&T%' AND is_active = true;

-- 2. Walmart (example - adjust based on actual format)
-- UPDATE merchant_prompts
-- SET extraction_rules = '{
--   "price_patterns": [
--     {
--       "pattern": "\\$(\\d+\\.\\d{2})",
--       "priority": 1,
--       "description": "Walmart price format",
--       "flags": "IGNORECASE"
--     }
--   ],
--   "skip_patterns": [
--     "^TOTAL",
--     "^Subtotal",
--     "^Tax",
--     "^SUBTOTAL",
--     "^TAX"
--   ],
--   "special_rules": {
--     "use_global_fp_match": false,
--     "min_fp_count": 0,
--     "category_identifiers": []
--   }
-- }'::jsonb
-- WHERE merchant_name ILIKE '%Walmart%' AND is_active = true;

-- 3. Costco (example - adjust based on actual format)
-- UPDATE merchant_prompts
-- SET extraction_rules = '{
--   "price_patterns": [
--     {
--       "pattern": "\\$(\\d+\\.\\d{2})",
--       "priority": 1,
--       "description": "Costco price format",
--       "flags": "IGNORECASE"
--     }
--   ],
--   "skip_patterns": [
--     "^TOTAL",
--     "^Subtotal",
--     "^Tax",
--     "^Membership"
--   ],
--   "special_rules": {
--     "use_global_fp_match": false,
--     "min_fp_count": 0,
--     "category_identifiers": []
--   }
-- }'::jsonb
-- WHERE merchant_name ILIKE '%Costco%' AND is_active = true;
